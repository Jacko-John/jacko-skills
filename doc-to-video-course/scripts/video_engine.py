"""Render narrated HTML, SVG and Canvas scenes to 1080p60 MP4."""
import asyncio
import base64
import errno
import hashlib
import http.server
import json
import os
import re
import socketserver
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import warnings
import wave
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import edge_tts
import imageio_ffmpeg
from playwright.sync_api import sync_playwright

from browser_runtime import find_chrome_exe, launch_chromium
from setup_katex import DEFAULT_CACHE, ensure_katex

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
DEFAULT_VOICE = "zh-CN-YunxiNeural"
DEFAULT_RATE = "-3%"
FPS = 60
DOM_ENTER_SEC = 0.7
SAMPLE_RATE = 48000
CHANNELS = 2
SAMPLE_WIDTH = 2  # 16-bit PCM


def get_cache_root() -> str:
    return os.environ.get("D2V_CACHE_DIR", DEFAULT_CACHE)


@dataclass
class Beat:
    """One synchronized narration, subtitle, and visual cue unit."""

    sub: str
    tts: Optional[str] = None
    cue: dict = field(default_factory=dict)
    pause_after: float = 0.35
    continuous: bool = False  # True if SVG/Canvas animates continuously across the beat
    marks: dict = field(default_factory=dict)  # key -> spoken phrase anchor resolved to beatTime (sec)


@dataclass
class Scene:
    """One visual board containing multiple sequential beats."""

    scene_id: str
    section_label: str
    html: str
    beats: List[Beat]
    js_init: str = ""
    js_frame: str = ""  # ctx.motion measures an interval against its originating beat.
    anim_settle_sec: float = DOM_ENTER_SEC
    clean_stage: bool = False  # True hides topbar chrome for centered distraction-free focus


@dataclass
class Episode:
    ep_num: str
    title: str
    subtitle: str
    filename: str
    scenes: List[Scene]


def _tts_cache_key(voice: str, rate: str, text: str) -> str:
    return hashlib.sha256(f"{voice}|{rate}|{text}".encode("utf-8")).hexdigest()[:24]


def _norm_match_text(s: str) -> str:
    return re.sub(r"[\s，。、；：！？“”‘’（）()《》【】\[\],.!?;:\"'·\-]+", "", s or "").lower()


def _resolve_beat_marks(
    tts_text: str, sub_text: str, words: List[dict], marks_spec: dict, speech_dur: float
) -> dict:
    """Resolve phrases to word onsets, warning when a legacy text estimate is used."""
    if not marks_spec:
        return {}
    joined_parts = []
    char_times = []
    for w in words:
        nw = _norm_match_text(w.get("text", ""))
        if not nw:
            continue
        t_sec = float(w.get("t", 0.0))
        for ch in nw:
            joined_parts.append(ch)
            char_times.append(t_sec)
    joined = "".join(joined_parts)

    resolved = {}
    cursor = 0
    for key, phrase in marks_spec.items():
        if isinstance(phrase, (int, float)):
            resolved[key] = float(phrase)
            continue
        needle = _norm_match_text(str(phrase))
        if not needle:
            resolved[key] = 0.0
            continue
        pos = joined.find(needle, cursor) if joined else -1
        if pos < 0 and joined:
            pos = joined.find(needle)
        if pos >= 0:
            resolved[key] = char_times[pos]
            cursor = pos + len(needle)
            continue
        # Preserve old specs that mark a notation appearing only in the subtitle.
        norm_tts = _norm_match_text(tts_text)
        norm_sub = _norm_match_text(sub_text)
        idx_tts = norm_tts.find(needle)
        if idx_tts >= 0 and norm_tts:
            resolved[key] = (idx_tts / float(len(norm_tts))) * speech_dur
        else:
            idx_sub = norm_sub.find(needle)
            if idx_sub >= 0 and norm_sub:
                resolved[key] = (idx_sub / float(len(norm_sub))) * speech_dur
            else:
                resolved[key] = 0.0
        warnings.warn(
            f"No spoken word boundary for {key}={phrase!r} in {tts_text!r}; "
            f"using fallback {resolved[key]:.3f}s.",
            stacklevel=2,
        )
    return resolved


async def _synthesize_take(
    text: str, voice: str, rate: str, need_words: bool, mp3: Path, staging: Path
) -> None:
    for attempt in range(4):
        try:
            words = []
            comm = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
            with mp3.open("wb") as f:
                async for chunk in comm.stream():
                    if chunk["type"] == "audio":
                        f.write(chunk["data"])
                    elif chunk["type"] == "WordBoundary":
                        words.append({
                            "t": chunk["offset"] / 10_000_000,
                            "d": chunk["duration"] / 10_000_000,
                            "text": chunk["text"],
                        })
            if need_words and not words:
                raise ValueError(f"TTS returned no word boundaries for {text!r}")
            break
        except Exception:
            if attempt == 3:
                raise
            await asyncio.sleep(1 + attempt)
    subprocess.run([
        FFMPEG, "-loglevel", "error", "-i", str(mp3),
        "-ar", str(SAMPLE_RATE), "-ac", str(CHANNELS),
        "-sample_fmt", "s16", str(staging / "audio.wav"),
    ], check=True)
    (staging / "words.json").write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")


async def _synth_one(
    sem: asyncio.Semaphore,
    text: str,
    wav_out: str,
    audio_cache_dir: str,
    voice: str,
    rate: str,
    need_words: bool = False,
) -> Tuple[float, List[dict]]:
    root = Path(audio_cache_dir)
    root.mkdir(parents=True, exist_ok=True)
    key = _tts_cache_key(voice, rate, text)
    take = root / key
    wav = take / "audio.wav"
    word_file = take / "words.json"
    if not take.exists():
        # Existing courses may have flat WAV caches from before word boundaries.
        old_wav = root / f"{key}.wav"
        old_words = root / f"{key}.words.json"
        old_has_words = old_words.is_file() and bool(json.loads(old_words.read_text(encoding="utf-8")))
        if old_wav.is_file() and (not need_words or old_has_words):
            wav, word_file = old_wav, old_words
        else:
            # Publish audio and timing from the same take together. Concurrent
            # workers can race on a phrase, but readers always get one complete pair.
            with tempfile.TemporaryDirectory(dir=root) as work:
                staging = Path(work) / "take"
                staging.mkdir()
                mp3 = Path(work) / "speech.mp3"
                async with sem:
                    await _synthesize_take(text, voice, rate, need_words, mp3, staging)
                try:
                    staging.rename(take)
                except OSError as exc:
                    if exc.errno not in (errno.EEXIST, errno.ENOTEMPTY):
                        raise
    words = json.loads(word_file.read_text(encoding="utf-8")) if word_file.exists() else []
    if need_words and not words:
        raise ValueError(f"Empty word boundaries in {word_file} for {text!r}")
    if Path(wav_out) != wav:
        shutil.copyfile(wav, wav_out)
    with wave.open(str(wav), "rb") as w:
        return w.getnframes() / float(w.getframerate()), words


async def synth_all_beats(
    episode: Episode,
    ep_work: str,
    audio_cache_dir: str,
    voice: str = DEFAULT_VOICE,
    rate: str = DEFAULT_RATE,
) -> List[dict]:
    sem = asyncio.Semaphore(6)
    tasks = []
    meta = []
    idx = 0
    for s_idx, sc in enumerate(episode.scenes):
        for b_idx, bt in enumerate(sc.beats):
            tts_text = bt.tts if bt.tts is not None else bt.sub
            wav_path = os.path.join(ep_work, f"beat_{idx:04d}.wav")
            tasks.append(
                _synth_one(
                    sem, tts_text, wav_path, audio_cache_dir, voice, rate,
                    need_words=any(isinstance(mark, str) for mark in bt.marks.values()),
                )
            )
            meta.append((idx, s_idx, b_idx, sc, bt, wav_path, tts_text))
            idx += 1

    results = await asyncio.gather(*tasks)
    timeline = []
    cur_sample = 0
    prev_step_key = None
    step_start_sec = 0.0
    for (i, s_idx, b_idx, sc, bt, wav_path, tts_text), (_dur, words) in zip(meta, results):
        with wave.open(wav_path, "rb") as w:
            n_audio_frames = w.getnframes()
        speech_dur = n_audio_frames / float(SAMPLE_RATE)
        pause_sec = bt.pause_after
        if b_idx == len(sc.beats) - 1:
            pause_sec = max(pause_sec, 0.55)
        n_pause_frames = int(round(pause_sec * SAMPLE_RATE))
        start_sec = cur_sample / SAMPLE_RATE
        speech_end_sec = (cur_sample + n_audio_frames) / SAMPLE_RATE
        total_end_sec = (cur_sample + n_audio_frames + n_pause_frames) / SAMPLE_RATE

        step_val = bt.cue.get("step", b_idx) if bt.cue else b_idx
        step_key = (s_idx, step_val)
        if step_key != prev_step_key:
            step_start_sec = start_sec
            prev_step_key = step_key

        resolved_marks = _resolve_beat_marks(tts_text, bt.sub, words, bt.marks, speech_dur)

        timeline.append(
            {
                "global_idx": i,
                "scene_idx": s_idx,
                "scene_id": sc.scene_id,
                "section_label": sc.section_label,
                "beat_idx": b_idx,
                "sub": bt.sub,
                "cue": bt.cue,
                "marks": resolved_marks,
                "continuous": bt.continuous,
                "anim_settle_sec": sc.anim_settle_sec,
                "wav_path": wav_path,
                "n_audio_samples": n_audio_frames,
                "n_pause_samples": n_pause_frames,
                "start_sec": start_sec,
                "step_start_sec": step_start_sec,
                "speech_end_sec": speech_end_sec,
                "end_sec": total_end_sec,
            }
        )
        cur_sample += n_audio_frames + n_pause_frames
    return timeline


def build_episode_wav_and_srt(
    timeline: List[dict], wav_out: str, srt_out: str
) -> float:
    total_samples = 0
    with wave.open(wav_out, "wb") as out_w:
        out_w.setnchannels(CHANNELS)
        out_w.setsampwidth(SAMPLE_WIDTH)
        out_w.setframerate(SAMPLE_RATE)
        for item in timeline:
            with wave.open(item["wav_path"], "rb") as in_w:
                out_w.writeframes(in_w.readframes(in_w.getnframes()))
            silence_bytes = b"\x00" * (
                item["n_pause_samples"] * CHANNELS * SAMPLE_WIDTH
            )
            out_w.writeframes(silence_bytes)
            total_samples += item["n_audio_samples"] + item["n_pause_samples"]

    def fmt_srt_time(sec: float) -> str:
        ms = int(round(sec * 1000))
        h = ms // 3600000
        ms %= 3600000
        m = ms // 60000
        ms %= 60000
        s = ms // 1000
        ms %= 1000
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    lines = []
    for idx, item in enumerate(timeline, 1):
        lines.append(f"{idx}")
        lines.append(
            f"{fmt_srt_time(item['start_sec'])} --> {fmt_srt_time(item['speech_end_sec'])}"
        )
        lines.append(item["sub"])
        lines.append("")
    with open(srt_out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return total_samples / float(SAMPLE_RATE)


SHARED_CSS = r"""
:root {
  --ink: #0f172a;
  --ink-2: #334155;
  --muted: #64748b;
  --line: rgba(15, 23, 42, 0.08);
  --bg: #faf9f6;
  --surface: rgba(255, 255, 255, 0.84);
  --surface-solid: #ffffff;
  --accent: #2563eb;
  --accent-deep: #1e40af;
  --accent-soft: rgba(37, 99, 235, 0.08);
  --warm: #e11d48;
  --warm-soft: rgba(225, 29, 72, 0.08);
  --coral: #d9483b;
  --green: #059669;
  --green-soft: rgba(5, 150, 105, 0.09);
  --amber: #d97706;
  --amber-soft: rgba(217, 119, 6, 0.09);
  --shadow-lg: 0 24px 60px -16px rgba(15, 23, 42, 0.10), 0 4px 16px -4px rgba(15, 23, 42, 0.04);
  --shadow-md: 0 12px 32px -10px rgba(15, 23, 42, 0.08), 0 2px 6px rgba(15, 23, 42, 0.03);
  --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
}
* { box-sizing: border-box; }
html, body {
  margin: 0;
  padding: 0;
  width: 1920px;
  height: 1080px;
  overflow: hidden;
  background: var(--bg);
  color: var(--ink);
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "PingFang SC", "Hiragino Sans GB", "Noto Sans CJK SC", sans-serif;
  -webkit-font-smoothing: antialiased;
}
.frame-shell {
  position: relative;
  width: 1920px;
  height: 1080px;
  display: flex;
  flex-direction: column;
  background:
    radial-gradient(1050px 580px at 88% 4%, rgba(37, 99, 235, 0.065), transparent 62%),
    radial-gradient(880px 520px at 8% 92%, rgba(217, 72, 59, 0.045), transparent 62%),
    radial-gradient(rgba(15, 23, 42, 0.042) 1px, transparent 1px) 0 0 / 28px 28px,
    var(--bg);
}

/* Minimal floating top bar */
.topbar {
  height: 68px;
  padding: 14px 68px 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: transparent;
}
.topbar-left { display: flex; align-items: center; gap: 14px; }
.ep-pill {
  background: var(--ink);
  color: #fff;
  font-weight: 700;
  font-size: 13.5px;
  padding: 4px 12px;
  border-radius: 999px;
  letter-spacing: 0.08em;
}
.course-tag {
  font-size: 14.5px;
  font-weight: 600;
  color: var(--muted);
  letter-spacing: 0.04em;
}
.sec-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--ink-2);
  margin-left: 4px;
  padding-left: 14px;
  border-left: 1.5px solid rgba(15, 23, 42, 0.14);
}
.topbar-right { display: flex; align-items: center; gap: 14px; }
.scene-dots { display: flex; gap: 7px; align-items: center; }
.scene-dot { width: 7px; height: 7px; border-radius: 999px; background: rgba(15, 23, 42, 0.14); }
.scene-dot.done { background: rgba(37, 99, 235, 0.42); }
.scene-dot.active { width: 24px; background: var(--accent); }
.prog-wrap { width: 140px; height: 4px; border-radius: 999px; background: rgba(15, 23, 42, 0.09); overflow: hidden; }
.prog-bar { height: 100%; width: 0%; background: linear-gradient(90deg, var(--accent), var(--coral)); }

.stage { position: relative; flex: 1; padding: 26px 68px 104px; overflow: hidden; }
.scene { display: none; width: 100%; height: 100%; }
.scene.active { display: flex; flex-direction: column; }

/* Cinema-grade lightweight subtitle strip */
.subtitle-wrap {
  position: absolute; left: 0; right: 0; bottom: 24px;
  display: flex; justify-content: center; pointer-events: none; z-index: 50;
}
.subtitle-box {
  background: rgba(255, 255, 255, 0.86);
  backdrop-filter: blur(18px);
  color: #0f172a;
  font-size: 25.5px;
  font-weight: 600;
  line-height: 1.42;
  letter-spacing: -0.005em;
  padding: 9px 28px;
  border-radius: 999px;
  max-width: 1520px;
  text-align: center;
  box-shadow: 0 8px 28px -6px rgba(15, 23, 42, 0.14), 0 1px 3px rgba(15, 23, 42, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.9);
}
.subtitle-box.empty { opacity: 0; }

/* Keynote Typography */
.eyebrow {
  font-size: 13.5px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--accent);
  margin-bottom: 6px;
}
.eyebrow.warm { color: var(--coral); }
.eyebrow.green { color: var(--green); }
.eyebrow.amber { color: var(--amber); }

.k-hero-title {
  font-size: 54px;
  font-weight: 800;
  line-height: 1.16;
  letter-spacing: -0.028em;
  color: var(--ink);
  margin: 0 0 14px;
}
.k-title {
  font-size: 36px;
  font-weight: 800;
  line-height: 1.22;
  letter-spacing: -0.022em;
  color: var(--ink);
  margin: 0 0 8px;
}
.k-sub {
  font-size: 21px;
  line-height: 1.55;
  color: var(--muted);
  margin: 0 0 22px;
  max-width: 64ch;
}
.h1 { font-size: 48px; font-weight: 800; line-height: 1.2; letter-spacing: -0.025em; margin: 0 0 14px; color: var(--ink); }
.h2 { font-size: 32px; font-weight: 700; line-height: 1.28; letter-spacing: -0.018em; margin: 0 0 10px; color: var(--ink); }
.h3 { font-size: 23px; font-weight: 700; line-height: 1.32; margin: 0 0 8px; color: var(--accent-deep); }
.lead { font-size: 21.5px; line-height: 1.58; color: var(--muted); margin: 0 0 18px; }

/* Layouts */
.split { display: grid; grid-template-columns: minmax(0, 1.02fr) minmax(0, 1fr); gap: 40px; flex: 1; min-height: 0; align-items: center; }
.split-wide { display: grid; grid-template-columns: minmax(0, 0.92fr) minmax(0, 1.22fr); gap: 38px; flex: 1; min-height: 0; align-items: center; }
.studio-split { display: grid; grid-template-columns: minmax(0, 0.96fr) minmax(0, 1.14fr); gap: 44px; flex: 1; min-height: 0; align-items: stretch; }
.studio-left { display: flex; flex-direction: column; justify-content: center; gap: 18px; padding-right: 6px; }
.studio-right { display: flex; flex-direction: column; justify-content: center; }

/* Borderless Keynote Surfaces (Apple / Linear feel) */
.card {
  background: var(--surface);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.95);
  border-radius: 22px;
  padding: 22px 26px;
  box-shadow: var(--shadow-md);
}
.card.soft-blue { background: rgba(239, 246, 255, 0.85); }
.card.soft-warm { background: rgba(255, 241, 242, 0.85); }
.card.soft-green { background: rgba(236, 253, 245, 0.85); }
.card.soft-amber { background: rgba(255, 251, 235, 0.85); }

/* Open editorial blocks (NO outer card border!) */
.note-block {
  padding: 8px 0 8px 20px;
  border-left: 3px solid rgba(37, 99, 235, 0.25);
}
.note-block.active-bar { border-left-color: var(--accent); }
.note-block.warm { border-left-color: var(--coral); }
.note-block.green { border-left-color: var(--green); }
.note-block.amber { border-left-color: var(--amber); }
.note-title { font-size: 20px; font-weight: 700; color: var(--ink); margin-bottom: 4px; }

.glass-panel {
  background: var(--surface-solid);
  border-radius: 24px;
  padding: 24px 26px;
  box-shadow: var(--shadow-lg);
  border: 1px solid rgba(15, 23, 42, 0.05);
}
.math-stage {
  background: rgba(255, 255, 255, 0.92);
  border-radius: 22px;
  padding: 22px 28px;
  box-shadow: var(--shadow-md);
  border: 1px solid rgba(37, 99, 235, 0.12);
  text-align: center;
  font-size: 26px;
}

.stack { display: flex; flex-direction: column; gap: 16px; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
.grid3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 22px; }
.grid4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 18px; }

.callout {
  border-left: 3.5px solid var(--accent);
  background: var(--accent-soft);
  padding: 13px 18px;
  border-radius: 0 14px 14px 0;
  font-size: 19px;
  line-height: 1.56;
  color: var(--ink-2);
}
.callout.warn { border-left-color: var(--coral); background: var(--warm-soft); }
.callout.ok { border-left-color: var(--green); background: var(--green-soft); }
.callout.amber { border-left-color: var(--amber); background: var(--amber-soft); }

.formula-box {
  background: rgba(255, 255, 255, 0.92);
  border-radius: 18px;
  padding: 16px 22px;
  font-size: 24px;
  text-align: center;
  box-shadow: var(--shadow-md);
}
.formula-box.hi {
  box-shadow: 0 16px 40px -12px rgba(37, 99, 235, 0.18), 0 0 0 1.5px rgba(37, 99, 235, 0.22);
}

.badge {
  display: inline-block;
  font-size: 13.5px;
  font-weight: 700;
  letter-spacing: 0.04em;
  padding: 4px 12px;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.06);
  color: var(--ink-2);
}
.badge.blue { background: var(--accent-soft); color: var(--accent-deep); }
.badge.warm { background: var(--warm-soft); color: var(--coral); }
.badge.green { background: var(--green-soft); color: var(--green); }
.badge.amber { background: var(--amber-soft); color: var(--amber); }

.kv-row { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 12px; }
.kv {
  background: rgba(15, 23, 42, 0.04);
  border-radius: 999px;
  padding: 6px 15px;
  font-size: 16.5px;
  color: var(--ink-2);
  font-variant-numeric: tabular-nums;
}
.kv b { color: var(--accent-deep); }
.kv.warn b { color: var(--coral); }
.kv.green b { color: var(--green); }

/* Sleek macOS-style dark code studio */
.code-window {
  background: #0b1120;
  border-radius: 18px;
  overflow: hidden;
  box-shadow: 0 22px 48px -12px rgba(15, 23, 42, 0.28);
}
.code-chrome {
  height: 36px;
  padding: 0 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: rgba(255, 255, 255, 0.04);
  border-bottom: 1px solid rgba(255, 255, 255, 0.07);
}
.win-dots { display: flex; gap: 7px; }
.win-dots span { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
.win-dots span:nth-child(1) { background: #ff5f57; }
.win-dots span:nth-child(2) { background: #febc2e; }
.win-dots span:nth-child(3) { background: #28c840; }
.win-title { font-family: var(--mono); font-size: 12.5px; color: #94a3b8; }

pre.code {
  background: #0b1120;
  color: #e2e8f0;
  border-radius: 16px;
  padding: 16px 22px;
  font-family: var(--mono);
  font-size: 17.5px;
  line-height: 1.5;
  white-space: normal;
  margin: 0;
  overflow: hidden;
}
.code-line { display: block; white-space: pre; padding: 2px 12px; margin: 1px -12px; border-radius: 6px; }
.code-line.hi { background: rgba(56, 189, 248, 0.18); box-shadow: inset 3px 0 0 #38bdf8; }
.code-line.warn { background: rgba(244, 63, 94, 0.18); box-shadow: inset 3px 0 0 #f43f5e; }
.c { color: #64748b; }
.k { color: #f59e0b; font-weight: 600; }
.s { color: #34d399; }

/* Minimalist Linear-style borderless data table */
table.data { width: 100%; border-collapse: collapse; font-size: 18px; font-variant-numeric: tabular-nums; }
table.data th, table.data td { padding: 12px 14px; border-bottom: 1px solid rgba(15, 23, 42, 0.07); text-align: right; }
table.data th:first-child, table.data td:first-child { text-align: left; }
table.data thead th { background: transparent; color: var(--muted); font-size: 14px; font-weight: 700; letter-spacing: 0.03em; border-bottom: 1.5px solid rgba(15, 23, 42, 0.12); }
table.data tr.hi td { background: rgba(37, 99, 235, 0.065); font-weight: 700; color: var(--ink); }
table.data tr.focus td { background: rgba(37, 99, 235, 0.11); }

/* Assertion-Evidence & Anchor Chips */
.assertion-title {
  font-size: 32px;
  font-weight: 800;
  line-height: 1.24;
  letter-spacing: -0.02em;
  color: var(--ink);
  margin: 0 0 10px;
}
.term-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 9px 15px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.90);
  border: 1px solid rgba(15, 23, 42, 0.08);
  box-shadow: 0 4px 14px -4px rgba(15, 23, 42, 0.06);
  font-size: 18px;
  color: var(--ink-2);
}
.term-chip b { color: var(--ink); }

/* Clean distraction-free mode & Full-Stage Centered Canvas */
.frame-shell.clean-mode .topbar { opacity: 0; pointer-events: none; }
.mg-stage {
  position: fixed;
  left: 0;
  top: 0;
  width: 1920px;
  height: 1080px;
  z-index: 1;
  pointer-events: none;
}
.center-stage {
  position: relative;
  z-index: 10;
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
}
.float-math {
  position: relative;
  z-index: 10;
  display: inline-block;
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(10px);
  border-radius: 20px;
  padding: 16px 32px;
  box-shadow: var(--shadow-md);
  border: 1px solid rgba(37, 99, 235, 0.14);
  font-size: 28px;
}
.code-spotlight {
  position: relative;
  z-index: 10;
  width: min(980px, 90%);
  margin: 0 auto;
  text-align: left;
}

/* Step transitions & declarative focus signaling */
.step { opacity: 0; transform: translateY(10px); }
.step.show { opacity: 1; transform: translateY(0); }
.step.focus { box-shadow: 0 18px 44px -12px rgba(37, 99, 235, 0.18), 0 0 0 1.5px rgba(37, 99, 235, 0.28) !important; }
.step.focus-warm { box-shadow: 0 18px 44px -12px rgba(217, 72, 59, 0.18), 0 0 0 1.5px rgba(217, 72, 59, 0.28) !important; }
.step.focus-green { box-shadow: 0 18px 44px -12px rgba(5, 150, 105, 0.18), 0 0 0 1.5px rgba(5, 150, 105, 0.28) !important; }
.focus-dim { opacity: 0.34 !important; }
.focus-active { box-shadow: 0 14px 36px -10px rgba(37, 99, 235, 0.22), 0 0 0 2px rgba(37, 99, 235, 0.38) !important; }
.focus-active.warm { box-shadow: 0 14px 36px -10px rgba(217, 72, 59, 0.22), 0 0 0 2px rgba(217, 72, 59, 0.38) !important; }
.focus-active.green { box-shadow: 0 14px 36px -10px rgba(5, 150, 105, 0.22), 0 0 0 2px rgba(5, 150, 105, 0.38) !important; }

.svg-card {
  background: var(--surface-solid);
  border-radius: 24px;
  padding: 22px 24px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  box-shadow: var(--shadow-lg);
  border: 1px solid rgba(15, 23, 42, 0.05);
}
svg { display: block; width: 100%; height: auto; overflow: visible; }
svg text { font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "PingFang SC", sans-serif; }
.mono-txt { font-family: var(--mono); }
p, li { font-size: 19.5px; line-height: 1.58; margin: 0.22em 0; color: var(--ink-2); }
ul.tight { padding-left: 1.2em; margin: 0.28em 0; }
.big-hero { flex: 1; display: flex; flex-direction: column; justify-content: center; padding: 0 36px; }
.quiz-opt { border: 1.5px solid rgba(15, 23, 42, 0.10); border-radius: 16px; padding: 16px 22px; font-size: 21px; background: #fff; margin: 10px 0; box-shadow: 0 2px 8px rgba(15, 23, 42, 0.03); }
.quiz-opt.right { border-color: var(--green); background: rgba(236, 253, 245, 0.9); font-weight: 700; }
.quiz-opt.wrong { border-color: var(--coral); background: rgba(255, 241, 242, 0.8); opacity: 0.72; }
"""

SHARED_JS = r"""
const NS = "http://www.w3.org/2000/svg";
function svgEl(tag, attrs, parent) {
  const n = document.createElementNS(NS, tag);
  if (attrs) {
    for (const k in attrs) {
      if (k === "text") n.textContent = attrs[k];
      else n.setAttribute(k, attrs[k]);
    }
  }
  if (parent) parent.appendChild(n);
  return n;
}
function clamp(v, a, b) { return Math.min(b, Math.max(a, v)); }
function easeOutCubic(t) { t = clamp(t, 0, 1); return 1 - Math.pow(1 - t, 3); }
function easeOutQuart(t) { t = clamp(t, 0, 1); return 1 - Math.pow(1 - t, 4); }
function easeInOut(t) { t = clamp(t, 0, 1); return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; }
function easeWhip(t) { t = clamp(t, 0, 1); return t < 0.5 ? 8 * t * t * t * t : 1 - Math.pow(-2 * t + 2, 4) / 2; }
function fmt(v, d) {
  const s = (d === undefined ? v.toFixed(3) : v.toFixed(d));
  return s.replace(/^-0(\.0+)?$/, (m) => m.slice(1));
}
function ensureGlobalSvgDefs() {
  let g = document.getElementById("global-svg-defs");
  if (!g) return;
  if (g.childNodes.length > 0) return;
  const palette = {
    blue: "#2563eb",
    red: "#d9483b",
    green: "#059669",
    amber: "#d97706",
    ink: "#0f172a",
    muted: "#94a3b8"
  };
  for (const [name, col] of Object.entries(palette)) {
    const mk = svgEl("marker", { id: "arr-" + name, viewBox: "0 0 10 10", refX: 8.5, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" }, g);
    svgEl("path", { d: "M 0 1.5 L 9 5 L 0 8.5 z", fill: col }, mk);

    const gr = svgEl("linearGradient", { id: "grad-" + name, x1: "0", y1: "0", x2: "0", y2: "1" }, g);
    svgEl("stop", { offset: "0%", "stop-color": col, "stop-opacity": "0.24" }, gr);
    svgEl("stop", { offset: "100%", "stop-color": col, "stop-opacity": "0.01" }, gr);
  }
}
function svgDefs(svg) {
  ensureGlobalSvgDefs();
  let defs = svg.querySelector("defs");
  if (!defs) defs = svgEl("defs", {}, svg);
  return defs;
}
function svgFrame(svg, o) {
  svg.setAttribute("viewBox", "0 0 " + o.w + " " + o.h);
  svg.innerHTML = "";
  svgDefs(svg);
  const p = o.pad;
  const sx = (v) => p.l + (v - o.x[0]) / (o.x[1] - o.x[0]) * (o.w - p.l - p.r);
  const sy = (v) => o.h - p.b - (v - o.y[0]) / (o.y[1] - o.y[0]) * (o.h - p.t - p.b);
  const nx = o.nx || 5, ny = o.ny || 4;
  // Clean Keynote axes: horizontal hairline guides only + crisp baseline
  for (let j = 0; j <= ny; j++) {
    const v = o.y[0] + (o.y[1] - o.y[0]) * j / ny;
    const isBase = j === 0;
    svgEl("line", {
      x1: p.l, x2: o.w - p.r, y1: sy(v), y2: sy(v),
      stroke: isBase ? "rgba(15, 23, 42, 0.22)" : "rgba(15, 23, 42, 0.065)",
      "stroke-width": isBase ? 1.5 : 1
    }, svg);
    if (o.ylab) svgEl("text", { x: p.l - 12, y: sy(v) + 5, "text-anchor": "end", fill: "#64748b", "font-size": 13.5, class: "mono-txt", text: fmt(v, o.ydec === undefined ? 2 : o.ydec) }, svg);
  }
  for (let i = 0; i <= nx; i++) {
    const v = o.x[0] + (o.x[1] - o.x[0]) * i / nx;
    if (o.xgrid) {
      svgEl("line", { x1: sx(v), x2: sx(v), y1: p.t, y2: o.h - p.b, stroke: "rgba(15, 23, 42, 0.05)", "stroke-width": 1 }, svg);
    }
    if (o.xlab) svgEl("text", { x: sx(v), y: o.h - p.b + 22, "text-anchor": "middle", fill: "#64748b", "font-size": 13.5, class: "mono-txt", text: o.xInt ? Math.round(v) : fmt(v, o.xdec === undefined ? 1 : o.xdec) }, svg);
  }
  if (o.title) svgEl("text", { x: p.l, y: p.t - 16, fill: "#0f172a", "font-size": 17.5, "font-weight": 700, text: o.title }, svg);
  return { sx, sy, svg };
}
function svgPolyline(svg, pts, color, w, dash) {
  if (pts.length < 2) return null;
  return svgEl("path", {
    d: "M" + pts.map((q) => q[0].toFixed(1) + " " + q[1].toFixed(1)).join(" L"),
    fill: "none", stroke: color, "stroke-width": w || 3.2, "stroke-dasharray": dash || "", "stroke-linejoin": "round", "stroke-linecap": "round"
  }, svg);
}
function svgAreaPolyline(svg, pts, color, gradId, baseY) {
  if (pts.length < 2) return null;
  const lineD = "M" + pts.map((q) => q[0].toFixed(1) + " " + q[1].toFixed(1)).join(" L");
  const areaD = lineD + ` L${pts[pts.length-1][0].toFixed(1)} ${baseY.toFixed(1)} L${pts[0][0].toFixed(1)} ${baseY.toFixed(1)} Z`;
  svgEl("path", { d: areaD, fill: `url(#${gradId})` }, svg);
  return svgEl("path", { d: lineD, fill: "none", stroke: color, "stroke-width": 3.4, "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);
}
function svgDot(svg, x, y, color, r, halo) {
  if (halo) {
    svgEl("circle", { cx: x, cy: y, r: (r || 6) * 2.1, fill: color, opacity: 0.16 }, svg);
  }
  return svgEl("circle", { cx: x, cy: y, r: r || 6, fill: color, stroke: "#fff", "stroke-width": 2.4 }, svg);
}
function svgCalloutArrow(svg, x1, y1, x2, y2, label, colorName, colorHex, anchor) {
  const mx = (x1 + x2) / 2, my = Math.min(y1, y2) - 18;
  svgEl("path", {
    d: `M${x1.toFixed(1)} ${y1.toFixed(1)} Q${mx.toFixed(1)} ${my.toFixed(1)} ${x2.toFixed(1)} ${y2.toFixed(1)}`,
    fill: "none", stroke: colorHex, "stroke-width": 2, "marker-end": `url(#arr-${colorName})`
  }, svg);
  svgEl("text", {
    x: x1, y: y1 - 8, "text-anchor": anchor || "middle",
    fill: colorHex, "font-size": 14.5, "font-weight": 700, text: label
  }, svg);
}
function svgLerp(a, b, t) { return a + (b - a) * clamp(t, 0, 1); }
function svgSubProgress(p, t0, t1) {
  if (t1 <= t0) return p >= t1 ? 1 : 0;
  return clamp((p - t0) / (t1 - t0), 0, 1);
}
function svgRevealPath(svg, pts, color, progress, w, dash) {
  const p = clamp(progress, 0, 1);
  if (pts.length < 2 || p <= 0) return null;
  if (p >= 1) return svgPolyline(svg, pts, color, w, dash);
  const segs = [];
  let totalLen = 0;
  for (let i = 1; i < pts.length; i++) {
    const dx = pts[i][0] - pts[i - 1][0], dy = pts[i][1] - pts[i - 1][1];
    const len = Math.hypot(dx, dy);
    segs.push(len);
    totalLen += len;
  }
  const targetLen = totalLen * p;
  const out = [pts[0]];
  let acc = 0;
  for (let i = 0; i < segs.length; i++) {
    if (acc + segs[i] <= targetLen) {
      out.push(pts[i + 1]);
      acc += segs[i];
    } else {
      const rem = segs[i] > 0 ? (targetLen - acc) / segs[i] : 0;
      out.push([
        pts[i][0] + (pts[i + 1][0] - pts[i][0]) * rem,
        pts[i][1] + (pts[i + 1][1] - pts[i][1]) * rem
      ]);
      break;
    }
  }
  return svgPolyline(svg, out, color, w, dash);
}
function svgBoxNode(svg, x, y, w, h, title, sub, opts) {
  const o = opts || {};
  const state = o.state || "idle";
  const tones = {
    idle: { fill: "#ffffff", stroke: "rgba(15, 23, 42, 0.16)", sw: 1.5, title: "#0f172a", op: 1 },
    active: { fill: "#eff6ff", stroke: "#2563eb", sw: 2.5, title: "#1e40af", op: 1 },
    warm: { fill: "#fff1f2", stroke: "#d9483b", sw: 2.5, title: "#be123c", op: 1 },
    green: { fill: "#ecfdf5", stroke: "#059669", sw: 2.5, title: "#047857", op: 1 },
    amber: { fill: "#fffbeb", stroke: "#d97706", sw: 2.5, title: "#b45309", op: 1 },
    dim: { fill: "#f8fafc", stroke: "rgba(15, 23, 42, 0.10)", sw: 1.2, title: "#64748b", op: 0.42 }
  };
  const st = tones[state] || tones.idle;
  const g = svgEl("g", { opacity: o.opacity !== undefined ? o.opacity : st.op }, svg);
  svgEl("rect", {
    x, y, width: w, height: h, rx: o.rx || 14,
    fill: o.fill || st.fill, stroke: o.stroke || st.stroke, "stroke-width": st.sw
  }, g);
  const cx = x + w / 2;
  const cy = sub ? y + h * 0.43 : y + h * 0.56;
  svgEl("text", {
    x: cx, y: cy, "text-anchor": "middle", fill: st.title,
    "font-size": o.titleSize || 16.5, "font-weight": 700, text: title
  }, g);
  if (sub) {
    svgEl("text", {
      x: cx, y: y + h * 0.72, "text-anchor": "middle", fill: "#64748b",
      "font-size": o.subSize || 13.5, class: o.subMono ? "mono-txt" : "", text: sub
    }, g);
  }
  return g;
}
function svgBadgePill(svg, x, y, text, opts) {
  const o = opts || {};
  const padX = o.padX || 12;
  const estW = Math.max(48, text.length * (o.charW || 9.5) + padX * 2);
  const h = o.h || 28;
  const bg = o.bg || "#eff6ff";
  const fg = o.fg || "#1e40af";
  const g = svgEl("g", { opacity: o.opacity !== undefined ? o.opacity : 1 }, svg);
  svgEl("rect", {
    x: x - estW / 2, y: y - h / 2, width: estW, height: h, rx: h / 2,
    fill: bg, stroke: o.stroke || "rgba(37, 99, 235, 0.22)", "stroke-width": 1.2
  }, g);
  svgEl("text", {
    x, y: y + 5, "text-anchor": "middle", fill: fg,
    "font-size": o.fontSize || 13.5, "font-weight": 700, class: o.mono ? "mono-txt" : "", text
  }, g);
  return g;
}
function svgConnector(svg, x1, y1, x2, y2, opts) {
  const o = opts || {};
  const p = o.progress === undefined ? 1 : clamp(o.progress, 0, 1);
  if (p <= 0.01) return null;
  const colorName = o.colorName || "blue";
  const colorHex = o.colorHex || "#2563eb";
  const ex = svgLerp(x1, x2, p);
  const ey = svgLerp(y1, y2, p);
  const curve = o.curve || 0;
  const mx = (x1 + x2) / 2;
  const my = (y1 + y2) / 2 - curve;
  const d = curve === 0
    ? `M${x1.toFixed(1)} ${y1.toFixed(1)} L${ex.toFixed(1)} ${ey.toFixed(1)}`
    : `M${x1.toFixed(1)} ${y1.toFixed(1)} Q${mx.toFixed(1)} ${my.toFixed(1)} ${ex.toFixed(1)} ${ey.toFixed(1)}`;
  const path = svgEl("path", {
    d, fill: "none", stroke: colorHex, "stroke-width": o.width || 2.4,
    "stroke-dasharray": o.dash || "",
    "marker-end": p > 0.85 ? `url(#arr-${colorName})` : "",
    opacity: o.opacity !== undefined ? o.opacity : 1
  }, svg);
  if (o.label && p > 0.6) {
    svgBadgePill(svg, mx, my - (curve === 0 ? 14 : 4), o.label, {
      bg: o.labelBg || "#ffffff", fg: colorHex, stroke: colorHex, fontSize: 12.5
    });
  }
  return path;
}

/* =========================================================================
 * Warm Alabaster Motion Graphics (MG) Canvas Toolkit
 * ========================================================================= */
const lerp = (a, b, t) => a + (b - a) * clamp(t, 0, 1);
const subP = (p, t0, t1) => clamp((p - t0) / Math.max(1e-5, t1 - t0), 0, 1);
const secP = (t, t0, dur) => clamp((t - t0) / Math.max(1e-5, dur), 0, 1);
function mgPulse(t, base, amp, speed) {
  return (base || 1) + (amp || 0.04) * Math.sin((t || 0) * (speed || 4.2));
}
function spring(t) {
  t = clamp(t, 0, 1);
  if (t === 0 || t === 1) return t;
  // Crisp easeOutBack (~6.5% settle overshoot for lively card/badge entrances)
  const s = 1.55;
  const u = t - 1;
  return 1 + u * u * ((s + 1) * u + s);
}
function mgPop(t) {
  t = clamp(t, 0, 1);
  const sp = spring(t);
  return {
    alpha: easeOutCubic(subP(t, 0, 0.42)),
    scale: 0.86 + 0.14 * sp,
    yOff: (1 - easeOutQuart(t)) * 20,
  };
}
function wiggle(tSec, freq, amp) {
  const t = Math.max(0, tSec);
  if (t <= 0) return 0;
  return Math.sin(t * (freq || 34)) * (amp || 8) * Math.exp(-2.6 * t);
}
function mgRoundRect(c, x, y, w, h, r) {
  r = Math.min(r || 14, w / 2, h / 2);
  c.beginPath();
  c.moveTo(x + r, y);
  c.lineTo(x + w - r, y);
  c.quadraticCurveTo(x + w, y, x + w, y + r);
  c.lineTo(x + w, y + h - r);
  c.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  c.lineTo(x + r, y + h);
  c.quadraticCurveTo(x, y + h, x, y + h - r);
  c.lineTo(x, y + r);
  c.quadraticCurveTo(x, y, x + r, y);
  c.closePath();
}
function mgClear(c) {
  c.clearRect(0, 0, 1920, 1080);
}
function mgCamera(c, scale, panX, panY, cx, cy) {
  const ox = cx === undefined ? 960 : cx;
  const oy = cy === undefined ? 500 : cy;
  c.translate(ox + (panX || 0), oy + (panY || 0));
  c.scale(scale || 1, scale || 1);
  c.translate(-ox, -oy);
}
function mgPill(c, cx, cy, text, opts) {
  const o = opts || {};
  const alpha = o.alpha === undefined ? 1 : o.alpha;
  if (alpha <= 0.01) return;
  c.save();
  c.globalAlpha *= alpha;
  c.font = o.font || "700 20px -apple-system, 'PingFang SC', sans-serif";
  const tw = c.measureText(text).width;
  const pw = tw + (o.padX || 32), ph = o.h || 40;
  mgRoundRect(c, cx - pw / 2, cy - ph / 2, pw, ph, ph / 2);
  c.fillStyle = o.bg || "rgba(255, 255, 255, 0.94)";
  c.fill();
  c.lineWidth = o.lw || 1.6;
  c.strokeStyle = o.stroke || "rgba(37, 99, 235, 0.28)";
  c.stroke();
  c.fillStyle = o.fg || "#1e40af";
  c.textAlign = "center";
  c.textBaseline = "middle";
  c.fillText(text, cx, cy + 1);
  c.restore();
}
function mgNode(c, x, y, w, h, title, sub, opts) {
  const o = opts || {};
  const state = o.state || "idle";
  const tones = {
    idle:   { bg: "rgba(255,255,255,0.95)", stroke: "rgba(15,23,42,0.14)", title: "#0f172a", op: 1, lw: 1.6 },
    active: { bg: "#eff6ff", stroke: "#2563eb", title: "#1e40af", op: 1, lw: 2.6 },
    warm:   { bg: "#fff1f2", stroke: "#d9483b", title: "#be123c", op: 1, lw: 2.6 },
    green:  { bg: "#ecfdf5", stroke: "#059669", title: "#047857", op: 1, lw: 2.6 },
    amber:  { bg: "#fffbeb", stroke: "#d97706", title: "#b45309", op: 1, lw: 2.6 },
    dim:    { bg: "rgba(248,250,252,0.9)", stroke: "rgba(15,23,42,0.08)", title: "#64748b", op: 0.36, lw: 1.2 },
  };
  const st = tones[state] || tones.idle;
  const alpha = o.alpha === undefined ? st.op : o.alpha * st.op;
  if (alpha <= 0.01) return;
  c.save();
  c.globalAlpha *= alpha;
  const dx = o.shakeX || 0, dy = o.shakeY || 0;
  if (o.scale !== undefined && o.scale !== 1) {
    const cx = x + dx + w / 2, cy = y + dy + h / 2;
    c.translate(cx, cy);
    c.scale(o.scale, o.scale);
    c.translate(-cx, -cy);
  }
  c.shadowColor = state === "active" ? "rgba(37,99,235,0.16)" : (state === "warm" ? "rgba(217,72,59,0.16)" : "rgba(15,23,42,0.08)");
  c.shadowBlur = state === "dim" ? 6 : 24;
  c.shadowOffsetY = 8;
  mgRoundRect(c, x + dx, y + dy, w, h, o.r || 18);
  c.fillStyle = o.bg || st.bg;
  c.fill();
  c.shadowColor = "transparent";
  c.lineWidth = st.lw;
  c.strokeStyle = o.stroke || st.stroke;
  c.stroke();
  c.fillStyle = st.title;
  c.textAlign = "center";
  c.textBaseline = "middle";
  c.font = o.titleFont || "700 22px -apple-system, 'PingFang SC', sans-serif";
  c.fillText(title, x + dx + w / 2, sub ? y + dy + h * 0.40 : y + dy + h * 0.52);
  if (sub) {
    c.fillStyle = "#64748b";
    c.font = o.subFont || "600 16px ui-monospace, SFMono-Regular, sans-serif";
    c.fillText(sub, x + dx + w / 2, y + dy + h * 0.70);
  }
  c.restore();
}
function mgArrow(c, x1, y1, x2, y2, opts) {
  const o = opts || {};
  const p = o.progress === undefined ? 1 : clamp(o.progress, 0, 1);
  const alpha = o.alpha === undefined ? 1 : o.alpha;
  if (p <= 0.02 || alpha <= 0.01) return;
  const col = o.color || "#2563eb";
  const curve = o.curve || 0;
  const mx = (x1 + x2) / 2, my = (y1 + y2) / 2 - curve;
  c.save();
  c.globalAlpha *= alpha;
  c.strokeStyle = col;
  c.fillStyle = col;
  c.lineWidth = o.lw || 3.2;
  c.lineCap = "round";
  if (o.dash) c.setLineDash(o.dash);
  c.beginPath();
  c.moveTo(x1, y1);
  let ex = lerp(x1, x2, p), ey = lerp(y1, y2, p);
  let tx = x1, ty = y1;
  if (curve === 0) {
    c.lineTo(ex, ey);
  } else {
    const steps = 36;
    for (let i = 1; i <= steps; i++) {
      const t = p * (i / steps);
      const mt = 1 - t;
      const qx = mt*mt*x1 + 2*mt*t*mx + t*t*x2;
      const qy = mt*mt*y1 + 2*mt*t*my + t*t*y2;
      if (i === steps - 1) { tx = qx; ty = qy; }
      ex = qx; ey = qy;
      c.lineTo(qx, qy);
    }
  }
  c.stroke();
  c.setLineDash([]);
  if (p > 0.08 && !o.noHead) {
    const ang = Math.atan2(ey - ty, ex - tx);
    const hl = (o.headLen || 13) * clamp((p - 0.08) / 0.28, 0, 1);
    if (hl > 1) {
      c.beginPath();
      c.moveTo(ex, ey);
      c.lineTo(ex - hl * Math.cos(ang - 0.42), ey - hl * Math.sin(ang - 0.42));
      c.lineTo(ex - hl * Math.cos(ang + 0.42), ey - hl * Math.sin(ang + 0.42));
      c.closePath();
      c.fill();
    }
  }
  if (o.label && p > 0.30) {
    mgPill(c, mx, my - (curve === 0 ? 22 : 10), o.label, {
      bg: o.labelBg || "rgba(255,255,255,0.94)", fg: col, stroke: col,
      font: "700 17px -apple-system, 'PingFang SC', sans-serif",
      alpha: clamp((p - 0.30) / 0.35, 0, 1),
    });
  }
  c.restore();
}
function mgPacket(c, pts, progress, label, opts) {
  if (!pts || pts.length < 2) return;
  const o = opts || {};
  const p = clamp(progress, 0, 1);
  const segs = [];
  let total = 0;
  for (let i = 1; i < pts.length; i++) {
    const len = Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
    segs.push(len);
    total += len;
  }
  let target = total * p, px = pts[0][0], py = pts[0][1];
  for (let i = 0; i < segs.length; i++) {
    if (target <= segs[i] || i === segs.length - 1) {
      const t = segs[i] > 0 ? clamp(target / segs[i], 0, 1) : 0;
      px = lerp(pts[i][0], pts[i + 1][0], t);
      py = lerp(pts[i][1], pts[i + 1][1], t);
      break;
    }
    target -= segs[i];
  }
  const col = o.color || "#2563eb";
  c.save();
  c.globalAlpha *= o.alpha === undefined ? 1 : o.alpha;
  c.fillStyle = col + "28";
  c.beginPath();
  c.arc(px, py, (o.r || 12) * 1.9, 0, Math.PI * 2);
  c.fill();
  c.fillStyle = col;
  c.strokeStyle = "#ffffff";
  c.lineWidth = 3;
  c.beginPath();
  c.arc(px, py, o.r || 12, 0, Math.PI * 2);
  c.fill();
  c.stroke();
  if (label) {
    mgPill(c, px, py - (o.r || 12) - 24, label, {
      bg: "#ffffff", fg: col, stroke: col, h: 32, padX: 20, font: "700 16px ui-monospace, 'PingFang SC', sans-serif"
    });
  }
  c.restore();
}
function mgAxes(c, b, opts) {
  const o = opts || {};
  const alpha = o.alpha === undefined ? 1 : o.alpha;
  if (alpha <= 0.01) return null;
  const sx = (v) => b.x + ((v - b.xmin) / (b.xmax - b.xmin)) * b.w;
  const sy = (v) => b.y + b.h - ((v - b.ymin) / (b.ymax - b.ymin)) * b.h;
  const baseY = sy(Math.max(b.ymin, 0));
  c.save();
  c.globalAlpha *= alpha;
  for (const yv of (o.yTicks || [])) {
    c.strokeStyle = "rgba(15, 23, 42, 0.07)";
    c.lineWidth = 1.2;
    c.beginPath();
    c.moveTo(b.x, sy(yv));
    c.lineTo(b.x + b.w, sy(yv));
    c.stroke();
    c.fillStyle = "#64748b";
    c.font = "500 17px ui-monospace, SFMono-Regular, monospace";
    c.textAlign = "right";
    c.textBaseline = "middle";
    c.fillText(yv.toFixed(o.ydec === undefined ? 1 : o.ydec), b.x - 16, sy(yv));
  }
  c.strokeStyle = "rgba(15, 23, 42, 0.28)";
  c.lineWidth = 2.2;
  c.beginPath();
  c.moveTo(b.x - 10, baseY);
  c.lineTo(b.x + b.w + 14, baseY);
  if (b.xmin <= 0 && b.xmax >= 0) {
    c.moveTo(sx(0), baseY + 14);
    c.lineTo(sx(0), b.y - 14);
  }
  c.stroke();
  if (o.xTicks) {
    c.fillStyle = "#475569";
    c.font = "600 18px ui-monospace, SFMono-Regular, monospace";
    c.textAlign = "center";
    c.textBaseline = "top";
    for (const xv of o.xTicks) {
      c.fillText(xv.toFixed(o.xdec === undefined ? 1 : o.xdec), sx(xv), baseY + 16);
    }
  }
  if (o.xLabel) {
    c.fillStyle = "#475569";
    c.font = "italic 700 22px Georgia, serif";
    c.textAlign = "left";
    c.textBaseline = "middle";
    c.fillText(o.xLabel, b.x + b.w + 22, baseY);
  }
  c.restore();
  return { sx, sy, baseY };
}
function mgCurve(c, sx, sy, fn, x0, x1, opts) {
  const o = opts || {};
  const p = o.progress === undefined ? 1 : clamp(o.progress, 0, 1);
  const alpha = o.alpha === undefined ? 1 : o.alpha;
  if (p <= 0.01 || alpha <= 0.01) return;
  const xEnd = lerp(x0, x1, p);
  const step = (x1 - x0) / (o.steps || 120);
  const pts = [];
  for (let x = x0; x <= xEnd + 1e-6; x += step) {
    pts.push([sx(x), sy(fn(x))]);
  }
  if (pts.length < 2) return;
  c.save();
  c.globalAlpha *= alpha;
  if (o.fill && o.baseY !== undefined) {
    c.beginPath();
    c.moveTo(pts[0][0], pts[0][1]);
    for (let i = 1; i < pts.length; i++) c.lineTo(pts[i][0], pts[i][1]);
    c.lineTo(pts[pts.length - 1][0], o.baseY);
    c.lineTo(pts[0][0], o.baseY);
    c.closePath();
    c.fillStyle = o.fill;
    c.fill();
  }
  c.strokeStyle = o.color || "#2563eb";
  c.lineWidth = o.lw || 4.2;
  c.lineCap = "round";
  c.lineJoin = "round";
  if (o.dash) c.setLineDash(o.dash);
  c.beginPath();
  c.moveTo(pts[0][0], pts[0][1]);
  for (let i = 1; i < pts.length; i++) c.lineTo(pts[i][0], pts[i][1]);
  c.stroke();
  c.restore();
}
function mgDot(c, x, y, color, r, halo) {
  c.save();
  if (halo) {
    c.fillStyle = color + "2b";
    c.beginPath();
    c.arc(x, y, (r || 8) * 2.1, 0, Math.PI * 2);
    c.fill();
  }
  c.fillStyle = color;
  c.strokeStyle = "#ffffff";
  c.lineWidth = 3;
  c.beginPath();
  c.arc(x, y, r || 8, 0, Math.PI * 2);
  c.fill();
  c.stroke();
  c.restore();
}
function mgFormula(c, cx, cy, text, opts) {
  const o = opts || {};
  const alpha = o.alpha === undefined ? 1 : o.alpha;
  if (alpha <= 0.01) return;
  c.save();
  c.globalAlpha *= alpha;
  c.font = o.font || "700 32px Georgia, 'Times New Roman', serif";
  const tw = c.measureText(text).width;
  const pw = tw + 56, ph = 74;
  c.shadowColor = "rgba(15, 23, 42, 0.08)";
  c.shadowBlur = 24;
  c.shadowOffsetY = 8;
  mgRoundRect(c, cx - pw / 2, cy - ph / 2, pw, ph, 20);
  c.fillStyle = "rgba(255, 255, 255, 0.96)";
  c.fill();
  c.shadowColor = "transparent";
  c.lineWidth = 1.6;
  c.strokeStyle = o.stroke || "rgba(37, 99, 235, 0.22)";
  c.stroke();
  c.fillStyle = o.fg || "#0f172a";
  c.textAlign = "center";
  c.textBaseline = "middle";
  c.fillText(text, cx, cy + 1);
  c.restore();
}
function mgHeader(c, cx, cy, eyebrow, title, opts) {
  const o = opts || {};
  const alpha = o.alpha === undefined ? 1 : o.alpha;
  if (alpha <= 0.01) return;
  c.save();
  c.globalAlpha *= alpha;
  c.textAlign = "center";
  c.textBaseline = "middle";
  if (eyebrow) {
    c.fillStyle = o.eyebrowColor || "#2563eb";
    c.font = o.eyebrowFont || "700 17px -apple-system, 'PingFang SC', sans-serif";
    c.fillText(eyebrow, cx, cy - (o.gap || 26));
  }
  if (title) {
    c.fillStyle = o.titleColor || "#0f172a";
    c.font = o.titleFont || "800 38px -apple-system, 'PingFang SC', sans-serif";
    c.fillText(title, cx, eyebrow ? cy + (o.gap || 20) : cy);
  }
  c.restore();
}
function mgPanel(c, x, y, w, h, title, opts) {
  const o = opts || {};
  const state = o.state || "green";
  const tones = {
    idle:   { bg: "rgba(255,255,255,0.92)", stroke: "rgba(15,23,42,0.14)", title: "#0f172a" },
    active: { bg: "#eff6ff", stroke: "#2563eb", title: "#1e40af" },
    warm:   { bg: "#fff1f2", stroke: "#d9483b", title: "#be123c" },
    green:  { bg: "#ecfdf5", stroke: "#059669", title: "#047857" },
    amber:  { bg: "#fffbeb", stroke: "#d97706", title: "#b45309" },
  };
  const st = tones[state] || tones.green;
  const alpha = o.alpha === undefined ? 1 : o.alpha;
  if (alpha <= 0.01) return;
  c.save();
  c.globalAlpha *= alpha;
  c.shadowColor = "rgba(15, 23, 42, 0.08)";
  c.shadowBlur = 28;
  c.shadowOffsetY = 10;
  mgRoundRect(c, x, y, w, h, o.r || 22);
  c.fillStyle = o.bg || st.bg;
  c.fill();
  c.shadowColor = "transparent";
  c.lineWidth = o.lw || 2.4;
  c.strokeStyle = o.stroke || st.stroke;
  c.stroke();
  if (title) {
    c.fillStyle = o.titleColor || st.title;
    c.font = o.titleFont || "700 26px -apple-system, 'PingFang SC', sans-serif";
    c.textAlign = "center";
    c.textBaseline = "middle";
    c.fillText(title, x + w / 2, y + (o.titleOffset || 44));
  }
  c.restore();
}
function _mgTokenizePy(src) {
  const kw = new Set(["def", "return", "for", "in", "if", "else", "elif", "import", "from", "as", "with", "None", "True", "False", "and", "or", "not"]);
  const out = [];
  const re = /([A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d+)?|"[^"]*"|'[^']*'|[^\sA-Za-z0-9_"']+|\s+)/g;
  let m;
  while ((m = re.exec(src)) !== null) {
    const tok = m[0];
    let color = "#e2e8f0";
    if (kw.has(tok)) color = "#c084fc";
    else if (/^\d/.test(tok)) color = "#fbbf24";
    else if (/^["']/.test(tok)) color = "#86efac";
    else if (/^[A-Za-z_][A-Za-z0-9_]*$/.test(tok)) {
      const rest = src.slice(re.lastIndex);
      if (rest.startsWith("(")) color = "#7dd3fc";
      else if (tok === "np" || tok === "torch" || tok === "dim") color = "#93c5fd";
    } else if (/^[=+\-*/(),.[\]:<>]+$/.test(tok.trim())) {
      color = "#94a3b8";
    }
    out.push({ text: tok, color });
  }
  return out;
}
function mgCodeWindow(c, x, y, w, h, opts) {
  const o = opts || {};
  const alpha = o.alpha === undefined ? 1 : o.alpha;
  if (alpha <= 0.01) return;
  const lines = o.lines || [];
  const headerH = o.headerH || 54;
  const padX = o.padX || 36;
  const rowH = o.rowH || Math.min(62, (h - headerH - 36) / Math.max(1, lines.length));
  const startY = y + headerH + 22;
  c.save();
  c.globalAlpha *= alpha;
  c.shadowColor = "rgba(15, 23, 42, 0.24)";
  c.shadowBlur = 40;
  c.shadowOffsetY = 16;
  mgRoundRect(c, x, y, w, h, o.r || 20);
  c.fillStyle = "#0b1120";
  c.fill();
  c.shadowColor = "transparent";
  c.lineWidth = 1.5;
  c.strokeStyle = "rgba(148, 163, 184, 0.22)";
  c.stroke();

  // macOS window chrome bar
  c.save();
  mgRoundRect(c, x, y, w, h, o.r || 20);
  c.clip();
  c.fillStyle = "rgba(255, 255, 255, 0.035)";
  c.fillRect(x, y, w, headerH);
  c.strokeStyle = "rgba(255, 255, 255, 0.08)";
  c.lineWidth = 1;
  c.beginPath();
  c.moveTo(x, y + headerH);
  c.lineTo(x + w, y + headerH);
  c.stroke();
  const dots = ["#ff5f56", "#ffbd2e", "#27c93f"];
  for (let i = 0; i < 3; i++) {
    c.fillStyle = dots[i];
    c.beginPath();
    c.arc(x + 28 + i * 24, y + headerH / 2, 7.5, 0, Math.PI * 2);
    c.fill();
  }
  if (o.filename) {
    c.fillStyle = "#94a3b8";
    c.font = "600 17px ui-monospace, SFMono-Regular, Menlo, monospace";
    c.textAlign = "right";
    c.textBaseline = "middle";
    c.fillText(o.filename, x + w - 26, y + headerH / 2);
  }
  c.restore();

  const codeFont = o.codeFont || "500 26px ui-monospace, SFMono-Regular, Menlo, monospace";
  const commentFont = o.commentFont || "500 22px -apple-system, 'PingFang SC', ui-monospace, monospace";
  const commentX = x + (o.commentOffset || Math.round(w * 0.56));
  for (let i = 0; i < lines.length; i++) {
    const ln = lines[i];
    const lineAlpha = ln.alpha === undefined ? 1 : clamp(ln.alpha, 0, 1);
    if (lineAlpha <= 0.01) continue;
    const hl = clamp(ln.highlight || 0, 0, 1);
    const ry = startY + i * rowH;
    const midY = ry + rowH / 2;
    c.save();
    c.globalAlpha *= lineAlpha;
    if (hl > 0.01) {
      mgRoundRect(c, x + 16, ry + 3, w - 32, rowH - 6, 11);
      c.fillStyle = `rgba(56, 189, 248, ${(0.14 * hl).toFixed(3)})`;
      c.fill();
      c.lineWidth = 1.6;
      c.strokeStyle = `rgba(56, 189, 248, ${(0.62 * hl).toFixed(3)})`;
      c.stroke();
      mgRoundRect(c, x + 16, ry + 10, 4.5, rowH - 20, 2);
      c.fillStyle = `rgba(56, 189, 248, ${hl.toFixed(3)})`;
      c.fill();
    }
    const tokens = ln.tokens || _mgTokenizePy(ln.code || "");
    c.font = codeFont;
    c.textAlign = "left";
    c.textBaseline = "middle";
    let cx = x + padX;
    for (const tok of tokens) {
      c.fillStyle = hl > 0.4 ? (tok.color === "#e2e8f0" ? "#f8fafc" : tok.color) : tok.color;
      c.fillText(tok.text, cx, midY);
      cx += c.measureText(tok.text).width;
    }
    if (ln.comment) {
      c.font = commentFont;
      c.fillStyle = hl > 0.4 ? "#94a3b8" : "#475569";
      c.fillText(ln.comment, Math.max(cx + 28, commentX), midY);
    }
    c.restore();
  }
  c.restore();
}
"""


def build_episode_html(
    episode: Episode, ep_html_path: str, katex_dir: Optional[str] = None,
    timeline: Optional[List[dict]] = None,
) -> None:
    katex_root = Path(ensure_katex(katex_dir)).resolve().as_uri()
    scenes_html = []
    dots_html = []
    for i, sc in enumerate(episode.scenes):
        dots_html.append(f'<span class="scene-dot" id="dot-{i}"></span>')
        scenes_html.append(f'<div class="scene" id="scene-{sc.scene_id}">{sc.html}</div>')

    init_calls = []
    frame_cases = []
    # Store the narration clock once in the page. Drawing an arbitrary frame,
    # including a backwards seek, never depends on having drawn the previous one.
    scene_clocks = [[] for _ in episode.scenes]
    for item in timeline or []:
        beats = scene_clocks[item["scene_idx"]]
        if not beats:
            scene_start = item["start_sec"]
        beats.append({
            "start": item["start_sec"] - scene_start,
            "speechDuration": item["speech_end_sec"] - item["start_sec"],
            "marks": item["marks"],
        })
    for sc in episode.scenes:
        if sc.js_init.strip():
            init_calls.append(
                f"(() => {{ const sceneEl = document.getElementById('scene-{sc.scene_id}');\n{sc.js_init}\n}})();"
            )
        if sc.js_frame.strip():
            frame_cases.append(
                f"if (sceneId === {json.dumps(sc.scene_id)}) {{\n{sc.js_frame}\n}}"
            )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<link id="course-math-css" rel="stylesheet" href="{katex_root}/katex.min.css">
<script src="{katex_root}/katex.min.js"></script>
<script src="{katex_root}/auto-render.min.js"></script>
<style id="course-stage-css">
{SHARED_CSS}
</style>
</head>
<body>
<svg width="0" height="0" style="position:absolute;width:0;height:0;overflow:hidden;pointer-events:none;"><defs id="global-svg-defs"></defs></svg>
<div class="frame-shell">
  <header class="topbar">
    <div class="topbar-left">
      <span class="ep-pill">EP {episode.ep_num}</span>
      <span class="course-tag">{episode.subtitle}</span>
      <span class="sec-title" id="sec-title">{episode.title}</span>
    </div>
    <div class="topbar-right">
      <div class="scene-dots">{''.join(dots_html)}</div>
      <div class="prog-wrap"><div class="prog-bar" id="prog-bar"></div></div>
    </div>
  </header>
  <main class="stage">
    {''.join(scenes_html)}
  </main>
  <div class="subtitle-wrap">
    <div class="subtitle-box" id="subtitle-box"></div>
  </div>
</div>
<script>
{SHARED_JS}

renderMathInElement(document.body, {{
  delimiters: [
    {{ left: "$$", right: "$$", display: true }},
    {{ left: "$", right: "$", display: false }}
  ],
  ignoredTags: ["pre", "code", "script", "style"],
  throwOnError: false
}});

const SCENE_IDS = {json.dumps([sc.scene_id for sc in episode.scenes])};
const SECTION_LABELS = {json.dumps([sc.section_label for sc in episode.scenes], ensure_ascii=False)};
const CLEAN_STAGES = {json.dumps([sc.clean_stage for sc in episode.scenes])};
const SCENE_CLOCKS = {json.dumps(scene_clocks)};

function motionProgress(sceneIdx, sceneTime, beatIdx, start, end) {{
  const beat = SCENE_CLOCKS[sceneIdx][beatIdx];
  if (!beat) throw new Error("Missing narration timing for scene " + SCENE_IDS[sceneIdx] + ", beat " + beatIdx);
  const from = typeof start === "string" ? beat.marks[start] : start;
  const to = end == null ? beat.speechDuration : (typeof end === "string" ? beat.marks[end] : end);
  if (!Number.isFinite(from) || !Number.isFinite(to) || to <= from) {{
    throw new Error("Invalid motion interval in " + SCENE_IDS[sceneIdx] + " beat " + beatIdx + ": " + start + " → " + end);
  }}
  return secP(sceneTime - beat.start, from, to - from);
}}

function motionElapsed(sceneIdx, sceneTime, beatIdx, start) {{
  const beat = SCENE_CLOCKS[sceneIdx][beatIdx];
  if (!beat) throw new Error("Missing narration timing for scene " + SCENE_IDS[sceneIdx] + ", beat " + beatIdx);
  const from = typeof start === "string" ? beat.marks[start] : start;
  if (!Number.isFinite(from)) {{
    throw new Error("Invalid motion anchor in " + SCENE_IDS[sceneIdx] + " beat " + beatIdx + ": " + start);
  }}
  return Math.max(0, (sceneTime - beat.start) - from);
}}

function motionSnap(sceneIdx, sceneTime, beatIdx, start, durSec) {{
  const dur = durSec === undefined ? 0.26 : durSec;
  return clamp(motionElapsed(sceneIdx, sceneTime, beatIdx, start) / Math.max(1e-4, dur), 0, 1);
}}

{chr(10).join(init_calls)}

window.seekToState = function(payload) {{
  const {{ sceneIdx, sceneId, beatIdx, cue, p, sceneTime, beatTime, stepTime, marks, sub, totalProgress }} = payload;
  document.getElementById("prog-bar").style.width = (totalProgress * 100).toFixed(2) + "%";
  document.getElementById("sec-title").textContent = SECTION_LABELS[sceneIdx] || "";
  const isClean = Boolean(CLEAN_STAGES[sceneIdx] || (cue && cue.clean));
  document.querySelector(".frame-shell").classList.toggle("clean-mode", isClean);
  for (let i = 0; i < SCENE_IDS.length; i++) {{
    const scEl = document.getElementById("scene-" + SCENE_IDS[i]);
    const dotEl = document.getElementById("dot-" + i);
    if (i === sceneIdx) {{
      scEl.classList.add("active");
      dotEl.className = "scene-dot active";
    }} else {{
      scEl.classList.remove("active");
      dotEl.className = i < sceneIdx ? "scene-dot done" : "scene-dot";
    }}
  }}
  const subBox = document.getElementById("subtitle-box");
  if (sub && sub.trim()) {{
    subBox.textContent = sub;
    subBox.classList.remove("empty");
  }} else {{
    subBox.textContent = "";
    subBox.classList.add("empty");
  }}

  const sceneEl = document.getElementById("scene-" + sceneId);
  const curStep = (cue && cue.step !== undefined) ? cue.step : beatIdx;
  const ease = easeInOut((stepTime === undefined ? beatTime : stepTime) / {DOM_ENTER_SEC});
  const isElVisible = (el) => {{
    if (el.hasAttribute("data-step")) {{
      const req = parseInt(el.getAttribute("data-step"), 10);
      if (curStep < req) return false;
    }}
    if (el.hasAttribute("data-hide-after")) {{
      const hideAfter = parseInt(el.getAttribute("data-hide-after"), 10);
      if (curStep > hideAfter) return false;
    }}
    return true;
  }};
  sceneEl.querySelectorAll("[data-step], [data-hide-after]").forEach((el) => {{
    const req = el.hasAttribute("data-step") ? parseInt(el.getAttribute("data-step"), 10) : 0;
    const visible = isElVisible(el);
    el.classList.toggle("show", visible);
    el.classList.remove("focus", "focus-warm", "focus-green");
    if (!visible) {{
      el.style.opacity = "0";
      el.style.transform = "translateY(14px)";
    }} else if (el.hasAttribute("data-step") && curStep === req && !el.hasAttribute("data-no-enter")) {{
      el.style.opacity = ease.toFixed(3);
      el.style.transform = "translateY(" + ((1 - ease) * 14).toFixed(1) + "px)";
    }} else if (el.hasAttribute("data-dim-past") && curStep > req) {{
      el.style.opacity = "0.52";
      el.style.transform = "translateY(0)";
    }} else {{
      el.style.opacity = "1";
      el.style.transform = "translateY(0)";
    }}
    if (visible && el.hasAttribute("data-step") && curStep === req && el.hasAttribute("data-focus-style")) {{
      el.classList.add(el.getAttribute("data-focus-style"));
    }} else if (visible && el.hasAttribute("data-step") && curStep === req && el.classList.contains("card")) {{
      el.classList.add("focus");
    }}
  }});

  // Declarative sub-element focus signaling: dim inactive siblings inside [data-focus-group]
  const focusSet = new Set();
  if (cue && cue.focus !== undefined && cue.focus !== null) {{
    const raw = Array.isArray(cue.focus) ? cue.focus : String(cue.focus).split(",");
    raw.forEach((s) => {{ const t = String(s).trim(); if (t) focusSet.add(t); }});
  }}
  const matchesFocus = (el) => {{
    const fid = el.getAttribute("data-focus-id");
    if (fid && focusSet.has(fid)) return true;
    const fs = el.getAttribute("data-focus-step") || el.getAttribute("data-focus-steps");
    if (fs) {{
      return fs.split(",").some((part) => parseInt(part.trim(), 10) === curStep);
    }}
    return false;
  }};
  sceneEl.querySelectorAll("[data-focus-step], [data-focus-steps], [data-focus-id]").forEach((el) => {{
    el.classList.remove("focus-active", "focus-dim", "warm", "green");
  }});
  sceneEl.querySelectorAll("[data-focus-group]").forEach((grp) => {{
    const items = Array.from(grp.querySelectorAll("[data-focus-step], [data-focus-steps], [data-focus-id]"))
      .filter((el) => isElVisible(el));
    const activeItems = items.filter(matchesFocus);
    if (activeItems.length > 0) {{
      items.forEach((el) => {{
        if (activeItems.includes(el)) {{
          el.classList.add("focus-active");
          const tone = el.getAttribute("data-focus-tone");
          if (tone === "warm" || tone === "green") el.classList.add(tone);
        }} else {{
          el.classList.add("focus-dim");
        }}
      }});
    }}
  }});
  if (focusSet.size > 0) {{
    sceneEl.querySelectorAll("[data-focus-id]").forEach((el) => {{
      if (isElVisible(el) && matchesFocus(el) && !el.closest("[data-focus-group]")) {{
        el.classList.add("focus-active");
        const tone = el.getAttribute("data-focus-tone");
        if (tone === "warm" || tone === "green") el.classList.add(tone);
      }}
    }});
  }}

  const ctx = {{ sceneEl, beatIdx, cue: cue || {{}}, p, sceneTime, beatTime,
    stepTime: stepTime === undefined ? beatTime : stepTime, marks: marks || {{}},
    motion: (originBeat, start, end) => motionProgress(sceneIdx, sceneTime, originBeat, start, end),
    snap: (originBeat, start, durSec) => motionSnap(sceneIdx, sceneTime, originBeat, start, durSec),
    elapsed: (originBeat, start) => motionElapsed(sceneIdx, sceneTime, originBeat, start),
  }};
  {chr(10).join(frame_cases)}
}};
</script>
</body>
</html>"""
    with open(ep_html_path, "w", encoding="utf-8") as f:
        f.write(html)


def _start_local_asset_server(work_dir: str, katex_dir: str) -> Tuple[socketserver.TCPServer, int]:
    """Serve ep_work and offline KaTeX assets over 127.0.0.1 so WebCodecs runs in a Secure Context."""

    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def translate_path(self, path: str) -> str:
            self.directory = work_dir
            if path.startswith("/katex/"):
                self.directory = katex_dir
                path = path[len("/katex"):]
            return super().translate_path(path)

        def log_message(self, format: str, *args) -> None:
            pass

    srv = socketserver.TCPServer(("127.0.0.1", 0), QuietHandler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, port


def _build_frame_entries(timeline: List[dict], total_dur: float, fps: int) -> List[dict]:
    scene_start_times = {}
    for item in timeline:
        if item["scene_idx"] not in scene_start_times:
            scene_start_times[item["scene_idx"]] = item["start_sec"]

    total_frames = int(round(total_dur * fps))
    entries = []
    t_idx = 0
    for f_idx in range(total_frames):
        t_sec = (f_idx + 0.5) / fps
        while t_idx + 1 < len(timeline) and t_sec >= timeline[t_idx]["end_sec"]:
            t_idx += 1
        item = timeline[t_idx]
        beat_time = max(0.0, t_sec - item["start_sec"])
        step_time = max(0.0, t_sec - item["step_start_sec"])
        speech_dur = max(0.01, item["speech_end_sec"] - item["start_sec"])
        p_beat = min(1.0, beat_time / speech_dur)
        scene_time = max(0.0, t_sec - scene_start_times[item["scene_idx"]])
        show_sub = item["sub"] if t_sec <= item["speech_end_sec"] + 0.12 else ""

        if item["continuous"]:
            # The narration may be holding while the last gesture is still settling.
            cache_key = None
        else:
            settled = step_time >= max(DOM_ENTER_SEC, item["anim_settle_sec"])
            cache_key = (item["global_idx"], bool(show_sub), True) if settled else None

        entries.append(
            {
                "payload": {
                    "sceneIdx": item["scene_idx"],
                    "sceneId": item["scene_id"],
                    "beatIdx": item["beat_idx"],
                    "cue": item["cue"],
                    "p": p_beat,
                    "sceneTime": scene_time,
                    "beatTime": beat_time,
                    "stepTime": step_time,
                    "marks": item.get("marks", {}),
                    "sub": show_sub,
                    "totalProgress": min(1.0, t_sec / total_dur),
                },
                "cache_key": cache_key,
            }
        )
    return entries


def _compose_frame(page, frame, return_page_png=False):
    """Draw the frame, supplying native page pixels if the compositor requests them."""
    request = page.evaluate("window.prepareVideoFrame", frame)
    while request:
        kind = request["kind"]
        options = {}
        if kind == "plate":
            options["style"] = ".scene.active > canvas.mg-stage { visibility: hidden !important; }"
        elif kind == "clip":
            options["clip"] = request["clip"]
        png = page.screenshot(type="png", **options)
        if return_page_png and kind == "page":
            return png
        request = page.evaluate("window.useCapture", {
            "kind": kind, "png": base64.b64encode(png).decode("ascii"),
        })
    return None


def _render_via_webcodecs(
    episode: Episode,
    ep_work: str,
    html_path: str,
    katex_dir: str,
    wav_path: str,
    out_mp4: str,
    entries: List[dict],
    fps: int,
    preset: str = "fast",
) -> Tuple[bool, int]:
    """Encode crisp constant-quantizer VP9 in Chromium via WebCodecs, then transcode cleanly to CRF-16 H.264 MP4."""
    with open(html_path, "r", encoding="utf-8") as f:
        raw_html = f.read()
    http_html_path = os.path.join(ep_work, "episode_http.html")
    with open(http_html_path, "w", encoding="utf-8") as f:
        f.write(raw_html.replace(Path(katex_dir).resolve().as_uri() + "/", "/katex/"))

    srv, port = _start_local_asset_server(ep_work, katex_dir)
    ivf_path = os.path.join(ep_work, "video.ivf")
    h264_path = os.path.join(ep_work, "video.h264")
    v_only_mp4 = os.path.join(ep_work, "video_only.mp4")

    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            page.goto(f"http://127.0.0.1:{port}/episode_http.html", wait_until="load")
            page.evaluate("document.fonts.ready")

            enc_mode = page.evaluate(
                """async (fps) => {
                  if (typeof VideoEncoder === "undefined") return null;
                  try {
                    const s = await VideoEncoder.isConfigSupported({
                      codec: "vp09.00.41.08", width: 1920, height: 1080,
                      bitrateMode: "quantizer", framerate: fps
                    });
                    if (s.supported) return { kind: "vp9", codec: "vp09.00.41.08" };
                  } catch (_) {}
                  for (const c of ["avc1.64002a", "avc1.4d002a"]) {
                    try {
                      const s = await VideoEncoder.isConfigSupported({
                        codec: c, width: 1920, height: 1080,
                        bitrate: 25_000_000, bitrateMode: "constant",
                        framerate: fps, avc: { format: "annexb" }
                      });
                      if (s.supported) return { kind: "avc", codec: c };
                    } catch (_) {}
                  }
                  return null;
                }""",
                fps,
            )
            if not enc_mode:
                browser.close()
                return False, 0

            use_vp9 = enc_mode["kind"] == "vp9"
            out_raw_path = ivf_path if use_vp9 else h264_path
            with open(out_raw_path, "wb") as raw_f:
                if use_vp9:
                    # Write IVF header (VP90, 1920x1080, fps/1)
                    raw_f.write(struct.pack("<4sHH4sHHII", b"DKIF", 0, 32, b"VP90", 1920, 1080, fps, 1))
                    raw_f.write(struct.pack("<II", len(entries), 0))

                    def write_chunk(pts_idx: int, b64: str) -> None:
                        buf = base64.b64decode(b64)
                        raw_f.write(struct.pack("<IQ", len(buf), pts_idx))
                        raw_f.write(buf)
                else:
                    def write_chunk(pts_idx: int, b64: str) -> None:
                        raw_f.write(base64.b64decode(b64))

                page.expose_function("__d2vWriteChunk", write_chunk)
                page.add_script_tag(path=str(Path(__file__).with_name("canvas_capture.js")))
                page.evaluate(
                    """({ encMode, fps }) => {
                      const compositor = createFrameCompositor();
                      const comp = compositor.canvas;
                      let current;

                      function u8ToB64(u8) {
                        let bin = "";
                        const chunk = 0x8000;
                        for (let i = 0; i < u8.length; i += chunk) {
                          bin += String.fromCharCode.apply(null, u8.subarray(i, i + chunk));
                        }
                        return btoa(bin);
                      }

                      const isVp9 = encMode.kind === "vp9";
                      let frameIndex = 0;
                      let written = 0;
                      let encoderError;
                      let pendingWrite = Promise.resolve();
                      const enc = new VideoEncoder({
                        output: (ch) => {
                          const buf = new Uint8Array(ch.byteLength);
                          ch.copyTo(buf);
                          const pts = Math.round(ch.timestamp * fps / 1000000);
                          written++;
                          const b64 = u8ToB64(buf);
                          pendingWrite = pendingWrite.then(() => window.__d2vWriteChunk(pts, b64));
                        },
                        error: (e) => { encoderError = e; }
                      });
                      if (isVp9) {
                        enc.configure({
                          codec: encMode.codec,
                          width: 1920,
                          height: 1080,
                          bitrateMode: "quantizer",
                          framerate: fps
                        });
                      } else {
                        enc.configure({
                          codec: encMode.codec,
                          width: 1920,
                          height: 1080,
                          bitrate: 25_000_000,
                          bitrateMode: "constant",
                          framerate: fps,
                          avc: { format: "annexb" }
                        });
                      }

                      const qp = fps >= 45 ? 12 : 16;
                      async function encode() {
                        const i = frameIndex++;
                        const ts = Math.round(i * 1000000 / fps);
                        const dur = Math.round((i + 1) * 1000000 / fps) - ts;
                        const vf = new VideoFrame(comp, {timestamp: ts, duration: dur, alpha: "discard"});
                        const keyFrame = current.isCut || i % fps === 0;
                        enc.encode(vf, isVp9 ? {keyFrame, vp9: {quantizer: qp}} : {keyFrame});
                        vf.close();
                        if (enc.encodeQueueSize > 16) await enc.flush();
                        if (encoderError) throw encoderError;
                      }

                      window.prepareVideoFrame = async frame => {
                        current = frame;
                        const request = compositor.prepare(frame);
                        if (!request) await encode();
                        return request;
                      };
                      window.useCapture = async image => {
                        const request = await compositor.supply(image);
                        if (!request) await encode();
                        return request;
                      };
                      window.finishEncoding = async () => {
                        if (encoderError) throw encoderError;
                        await enc.flush();
                        enc.close();
                        await pendingWrite;
                        return written;
                      };
                    }""",
                    {"encMode": enc_mode, "fps": fps},
                )
                previous_scene = None
                for entry in entries:
                    payload = entry["payload"]
                    frame = dict(payload, isCut=payload["sceneIdx"] != previous_scene)
                    previous_scene = payload["sceneIdx"]
                    _compose_frame(page, frame)
                rendered_count = len(entries)
                written = page.evaluate("window.finishEncoding()")
                if written != len(entries):
                    raise RuntimeError(f"Encoder wrote {written} of {len(entries)} frames")
            browser.close()

        if use_vp9:
            # Transcode lossless-grade VP9 IVF -> crisp CRF-16 H.264 MP4 (no hardware VBR smearing)
            subprocess.run(
                [
                    FFMPEG, "-y", "-loglevel", "error",
                    "-i", ivf_path, "-i", wav_path,
                    "-c:v", "libx264", "-preset", "veryfast" if preset == "veryfast" else "fast",
                    "-crf", "16" if fps >= 30 else "18", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k",
                    "-shortest", "-movflags", "+faststart", out_mp4,
                ],
                check=True,
            )
        else:
            subprocess.run(
                [
                    FFMPEG, "-y", "-loglevel", "error",
                    "-r", str(fps), "-f", "h264", "-i", h264_path,
                    "-c:v", "copy", v_only_mp4,
                ],
                check=True,
            )
            subprocess.run(
                [
                    FFMPEG, "-y", "-loglevel", "error",
                    "-i", v_only_mp4, "-i", wav_path,
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-shortest", "-movflags", "+faststart", out_mp4,
                ],
                check=True,
            )
        return True, rendered_count
    finally:
        srv.shutdown()
        srv.server_close()


def _render_via_screenshots(
    episode: Episode,
    html_path: str,
    wav_path: str,
    out_mp4: str,
    entries: List[dict],
    fps: int,
    preset: str,
) -> int:
    """Fallback frame-by-frame Playwright screenshot -> ffmpeg pipeline."""
    cmd = [
        FFMPEG,
        "-y",
        "-loglevel",
        "error",
        "-f",
        "image2pipe",
        "-vcodec",
        "png",
        "-framerate",
        str(fps),
        "-i",
        "-",
        "-i",
        wav_path,
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        "17" if fps >= 24 else "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        "-movflags",
        "+faststart",
        out_mp4,
    ]
    with sync_playwright() as p, tempfile.TemporaryFile() as errors:
        browser = launch_chromium(p)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.goto(Path(html_path).resolve().as_uri(), wait_until="load")
        page.evaluate("document.fonts.ready")
        page.add_script_tag(path=str(Path(__file__).with_name("canvas_capture.js")))
        page.evaluate("""() => {
            const compositor = createFrameCompositor();
            window.prepareVideoFrame = compositor.prepare;
            window.useCapture = compositor.supply;
            window.framePNG = () => compositor.canvas.toDataURL("image/png").split(",")[1];
        }""")
        with subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=errors) as proc:
            try:
                for entry in entries:
                    png = _compose_frame(page, entry["payload"], return_page_png=True)
                    if png is None:
                        png = base64.b64decode(page.evaluate("window.framePNG()"))
                    proc.stdin.write(png)
            finally:
                proc.stdin.close()
            if proc.wait():
                errors.seek(0)
                raise RuntimeError(f"ffmpeg failed for EP {episode.ep_num}: {errors.read().decode(errors='replace')}")
        browser.close()
    return len(entries)


def render_episode(
    episode: Episode,
    out_dir: str,
    work_dir: Optional[str] = None,
    voice: str = DEFAULT_VOICE,
    rate: str = DEFAULT_RATE,
    katex_dir: Optional[str] = None,
    fps: int = FPS,
    preset: str = "fast",
) -> dict:
    t_start = time.time()
    cache_root = get_cache_root()
    work_root = work_dir or os.path.join(cache_root, "episode_build")
    audio_cache_dir = os.path.join(cache_root, "audio_cache")
    os.makedirs(work_root, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)
    out_mp4 = os.path.join(out_dir, episode.filename)
    srt_path = os.path.splitext(out_mp4)[0] + ".srt"

    # A second course or process can use the same episode number concurrently.
    with tempfile.TemporaryDirectory(dir=work_root) as ep_work, \
            tempfile.TemporaryDirectory(prefix=".render-", dir=out_dir) as staging:
        print(
            f"[EP {episode.ep_num}] Synthesizing audio ({sum(len(s.beats) for s in episode.scenes)} beats)...",
            flush=True,
        )
        timeline = asyncio.run(
            synth_all_beats(episode, ep_work, audio_cache_dir, voice=voice, rate=rate)
        )
        wav_path = os.path.join(ep_work, "full.wav")
        staged_srt = os.path.join(staging, "subtitles.srt")
        total_dur = build_episode_wav_and_srt(timeline, wav_path, staged_srt)
        entries = _build_frame_entries(timeline, total_dur, fps)
        total_frames = len(entries)
        print(
            f"[EP {episode.ep_num}] Audio ready: {total_dur:.2f}s ({total_frames} frames @ {fps}fps)",
            flush=True,
        )

        katex_root = ensure_katex(katex_dir)
        html_path = os.path.join(ep_work, "episode.html")
        build_episode_html(episode, html_path, katex_dir=katex_root, timeline=timeline)

        staged_mp4 = os.path.join(staging, "video.mp4")
        ok_wc, rendered_count = _render_via_webcodecs(
            episode, ep_work, html_path, katex_root, wav_path, staged_mp4, entries, fps, preset
        )
        mode_tag = "WebCodecs"
        if not ok_wc:
            mode_tag = "Screenshots"
            rendered_count = _render_via_screenshots(
                episode, html_path, wav_path, staged_mp4, entries, fps, preset
            )

        size_mb = os.path.getsize(staged_mp4) / (1024 * 1024)
        with publication_lock(out_dir):
            publish_files([(Path(staged_mp4), Path(out_mp4)), (Path(staged_srt), Path(srt_path))])

    elapsed = time.time() - t_start
    print(
        f"[EP {episode.ep_num}] Rendered [{mode_tag}] ({size_mb:.1f} MB, {total_dur:.1f}s, "
        f"{rendered_count}/{total_frames} frames drawn in {elapsed:.1f}s)",
        flush=True,
    )
    return {
        "ep_num": episode.ep_num,
        "mp4": out_mp4,
        "srt": srt_path,
        "duration_sec": total_dur,
        "size_mb": size_mb,
        "rendered_frames": rendered_count,
        "total_frames": total_frames,
    }


@contextmanager
def publication_lock(out_dir):
    """Serialize writers on a stable lock file. Windows locks a byte, Unix the file."""
    with open(Path(out_dir) / ".course-publish.lock", "a+b") as lock:
        if os.name == "nt":
            import msvcrt
            if lock.seek(0, os.SEEK_END) == 0:
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        yield
        # Closing the descriptor releases the lock, including on exceptions.


def publish_files(files):
    """Replace a completed set while holding publication_lock; restore older files on failure."""
    backups = {}
    recovery_dirs = {}
    replaced = []
    cleanup = True
    try:
        for index, (staged, target) in enumerate(files):
            if target in backups:
                raise ValueError(f"Duplicate publication path: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            backup = None
            if os.path.lexists(target):
                if not target.is_file() and not target.is_symlink():
                    raise IsADirectoryError(str(target))
                if target.parent not in recovery_dirs:
                    recovery_dirs[target.parent] = Path(tempfile.mkdtemp(prefix=".publish-backup-", dir=target.parent))
                backup = recovery_dirs[target.parent] / str(index)
                try:
                    os.link(target, backup, follow_symlinks=False)
                except (OSError, NotImplementedError):
                    shutil.copy2(target, backup, follow_symlinks=False)
            backups[target] = backup
            os.replace(staged, target)
            replaced.append(target)
    except BaseException:
        errors = []
        for target in reversed(replaced):
            try:
                if backups[target] is None:
                    target.unlink()
                else:
                    os.replace(backups[target], target)
            except OSError as err:
                errors.append(str(err))
        if errors:
            cleanup = False
            raise RuntimeError(f"Rollback failed: {errors}. Retained backups: {list(recovery_dirs.values())}")
        raise
    finally:
        if cleanup:
            for directory in recovery_dirs.values():
                shutil.rmtree(directory)

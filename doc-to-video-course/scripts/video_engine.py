"""Reusable 1080p @ 30fps HTML/KaTeX/SVG + edge-tts + ffmpeg MP4 video rendering engine (Modern Keynote Studio Edition)."""
import asyncio
import glob
import hashlib
import json
import os
import subprocess
import time
import wave
from dataclasses import dataclass, field
from typing import List, Optional

import edge_tts
import imageio_ffmpeg
from playwright.sync_api import sync_playwright

from setup_katex import DEFAULT_CACHE, ensure_katex

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
DEFAULT_VOICE = "zh-CN-YunxiNeural"
DEFAULT_RATE = "-3%"
FPS = 30
SAMPLE_RATE = 48000
CHANNELS = 2
SAMPLE_WIDTH = 2  # 16-bit PCM


def get_cache_root() -> str:
    return os.environ.get("D2V_CACHE_DIR", DEFAULT_CACHE)


def find_chrome_exe() -> str:
    candidates = sorted(
        glob.glob(
            os.path.expanduser(
                "~/Library/Caches/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell"
            )
        )
    )
    if candidates:
        return candidates[-1]
    for path in (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
    ):
        if os.path.exists(path):
            return path
    raise FileNotFoundError(
        "No Chromium/Chrome executable found. Install Chrome or run `playwright install chromium`."
    )


@dataclass
class Beat:
    """One synchronized narration, subtitle, and visual cue unit."""

    sub: str
    tts: Optional[str] = None
    cue: dict = field(default_factory=dict)
    pause_after: float = 0.35
    continuous: bool = False  # True if SVG/Canvas animates continuously across the beat


@dataclass
class Scene:
    """One visual board containing multiple sequential beats."""

    scene_id: str
    section_label: str
    html: str
    beats: List[Beat]
    js_init: str = ""
    js_frame: str = ""  # Receives ctx: {sceneEl, beatIdx, cue, p, sceneTime, beatTime, stepTime}
    anim_settle_sec: float = 0.75


@dataclass
class Episode:
    ep_num: str
    title: str
    subtitle: str
    filename: str
    scenes: List[Scene]


def _tts_cache_key(voice: str, rate: str, text: str) -> str:
    return hashlib.sha256(f"{voice}|{rate}|{text}".encode("utf-8")).hexdigest()[:24]


async def _synth_one(
    sem: asyncio.Semaphore,
    text: str,
    wav_out: str,
    audio_cache_dir: str,
    voice: str,
    rate: str,
) -> float:
    os.makedirs(audio_cache_dir, exist_ok=True)
    key = _tts_cache_key(voice, rate, text)
    cached_wav = os.path.join(audio_cache_dir, f"{key}.wav")
    if not os.path.exists(cached_wav):
        mp3_tmp = os.path.join(audio_cache_dir, f"{key}.mp3")
        async with sem:
            for attempt in range(4):
                try:
                    comm = edge_tts.Communicate(text, voice, rate=rate)
                    await comm.save(mp3_tmp)
                    break
                except Exception:
                    if attempt == 3:
                        raise
                    await asyncio.sleep(1.0 + attempt)
        subprocess.run(
            [
                FFMPEG,
                "-y",
                "-i",
                mp3_tmp,
                "-ar",
                str(SAMPLE_RATE),
                "-ac",
                str(CHANNELS),
                "-sample_fmt",
                "s16",
                cached_wav,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    if wav_out != cached_wav:
        with open(cached_wav, "rb") as src, open(wav_out, "wb") as dst:
            dst.write(src.read())
    with wave.open(cached_wav, "rb") as w:
        return w.getnframes() / float(w.getframerate())


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
                _synth_one(sem, tts_text, wav_path, audio_cache_dir, voice, rate)
            )
            meta.append((idx, s_idx, b_idx, sc, bt, wav_path))
            idx += 1

    durations = await asyncio.gather(*tasks)
    timeline = []
    cur_sample = 0
    prev_step_key = None
    step_start_sec = 0.0
    for (i, s_idx, b_idx, sc, bt, wav_path), _dur in zip(meta, durations):
        with wave.open(wav_path, "rb") as w:
            n_audio_frames = w.getnframes()
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

        timeline.append(
            {
                "global_idx": i,
                "scene_idx": s_idx,
                "scene_id": sc.scene_id,
                "section_label": sc.section_label,
                "beat_idx": b_idx,
                "sub": bt.sub,
                "cue": bt.cue,
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

/* Step transitions */
.step { opacity: 0; transform: translateY(10px); }
.step.show { opacity: 1; transform: translateY(0); }
.step.focus { box-shadow: 0 18px 44px -12px rgba(37, 99, 235, 0.18), 0 0 0 1.5px rgba(37, 99, 235, 0.28) !important; }
.step.focus-warm { box-shadow: 0 18px 44px -12px rgba(217, 72, 59, 0.18), 0 0 0 1.5px rgba(217, 72, 59, 0.28) !important; }
.step.focus-green { box-shadow: 0 18px 44px -12px rgba(5, 150, 105, 0.18), 0 0 0 1.5px rgba(5, 150, 105, 0.28) !important; }

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
function easeInOut(t) { t = clamp(t, 0, 1); return t < 0.5 ? 4*t*t*t : 1 - Math.pow(-2*t+2, 3)/2; }
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
"""


def build_episode_html(
    episode: Episode, ep_html_path: str, katex_dir: Optional[str] = None
) -> None:
    katex_root = ensure_katex(katex_dir)
    scenes_html = []
    dots_html = []
    for i, sc in enumerate(episode.scenes):
        dots_html.append(f'<span class="scene-dot" id="dot-{i}"></span>')
        scenes_html.append(f'<div class="scene" id="scene-{sc.scene_id}">{sc.html}</div>')

    init_calls = []
    frame_cases = []
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
<link rel="stylesheet" href="file://{katex_root}/katex.min.css">
<script src="file://{katex_root}/katex.min.js"></script>
<script src="file://{katex_root}/auto-render.min.js"></script>
<style>
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

{chr(10).join(init_calls)}

window.seekToState = function(payload) {{
  const {{ sceneIdx, sceneId, beatIdx, cue, p, sceneTime, beatTime, stepTime, sub, totalProgress }} = payload;
  document.getElementById("prog-bar").style.width = (totalProgress * 100).toFixed(2) + "%";
  document.getElementById("sec-title").textContent = SECTION_LABELS[sceneIdx] || "";
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
  const enterT = Math.min(1, Math.max(0, (stepTime === undefined ? beatTime : stepTime) / 0.42));
  const ease = 1 - Math.pow(1 - enterT, 3);
  sceneEl.querySelectorAll("[data-step]").forEach((el) => {{
    const req = parseInt(el.getAttribute("data-step"), 10);
    const visible = curStep >= req;
    el.classList.toggle("show", visible);
    el.classList.remove("focus", "focus-warm", "focus-green");
    if (!visible) {{
      el.style.opacity = "0";
      el.style.transform = "translateY(14px)";
    }} else if (curStep === req && !el.hasAttribute("data-no-enter")) {{
      el.style.opacity = ease.toFixed(3);
      el.style.transform = "translateY(" + ((1 - ease) * 14).toFixed(1) + "px)";
    }} else if (el.hasAttribute("data-dim-past") && curStep > req) {{
      el.style.opacity = "0.52";
      el.style.transform = "translateY(0)";
    }} else {{
      el.style.opacity = "1";
      el.style.transform = "translateY(0)";
    }}
    if (curStep === req && el.hasAttribute("data-focus-style")) {{
      el.classList.add(el.getAttribute("data-focus-style"));
    }} else if (curStep === req && el.classList.contains("card")) {{
      el.classList.add("focus");
    }}
  }});

  const ctx = {{ sceneEl, beatIdx, cue: cue || {{}}, p, sceneTime, beatTime, stepTime: stepTime === undefined ? beatTime : stepTime }};
  {chr(10).join(frame_cases)}
}};
</script>
</body>
</html>"""
    with open(ep_html_path, "w", encoding="utf-8") as f:
        f.write(html)


def render_episode(
    episode: Episode,
    out_dir: str,
    work_dir: Optional[str] = None,
    voice: str = DEFAULT_VOICE,
    rate: str = DEFAULT_RATE,
    katex_dir: Optional[str] = None,
) -> dict:
    t_start = time.time()
    cache_root = get_cache_root()
    work_root = work_dir or os.path.join(cache_root, "episode_build")
    audio_cache_dir = os.path.join(cache_root, "audio_cache")
    os.makedirs(out_dir, exist_ok=True)
    ep_work = os.path.join(work_root, f"ep_{episode.ep_num}")
    os.makedirs(ep_work, exist_ok=True)

    print(
        f"[EP {episode.ep_num}] Synthesizing audio ({sum(len(s.beats) for s in episode.scenes)} beats)...",
        flush=True,
    )
    timeline = asyncio.run(
        synth_all_beats(episode, ep_work, audio_cache_dir, voice=voice, rate=rate)
    )
    wav_path = os.path.join(ep_work, "full.wav")
    srt_path = os.path.join(out_dir, os.path.splitext(episode.filename)[0] + ".srt")
    total_dur = build_episode_wav_and_srt(timeline, wav_path, srt_path)
    total_frames = int(round(total_dur * FPS))
    print(
        f"[EP {episode.ep_num}] Audio ready: {total_dur:.2f}s ({total_frames} frames @ {FPS}fps)",
        flush=True,
    )

    html_path = os.path.join(ep_work, "episode.html")
    build_episode_html(episode, html_path, katex_dir=katex_dir)

    out_mp4 = os.path.join(out_dir, episode.filename)
    cmd = [
        FFMPEG,
        "-y",
        "-loglevel",
        "error",
        "-f",
        "image2pipe",
        "-vcodec",
        "mjpeg",
        "-framerate",
        str(FPS),
        "-i",
        "-",
        "-i",
        wav_path,
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "17",
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
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
    )

    scene_start_times = {}
    for item in timeline:
        if item["scene_idx"] not in scene_start_times:
            scene_start_times[item["scene_idx"]] = item["start_sec"]

    chrome_exe = find_chrome_exe()
    t_idx = 0
    last_cache_key = None
    last_jpg = None
    rendered_count = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chrome_exe)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.goto("file://" + html_path, wait_until="load")
        page.evaluate("document.fonts.ready")

        for f_idx in range(total_frames):
            t_sec = (f_idx + 0.5) / FPS
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
                cache_key = None
            else:
                settled = step_time > item["anim_settle_sec"]
                cache_key = (item["global_idx"], bool(show_sub), True) if settled else None

            if (
                cache_key is not None
                and cache_key == last_cache_key
                and last_jpg is not None
            ):
                proc.stdin.write(last_jpg)
            else:
                payload = {
                    "sceneIdx": item["scene_idx"],
                    "sceneId": item["scene_id"],
                    "beatIdx": item["beat_idx"],
                    "cue": item["cue"],
                    "p": p_beat,
                    "sceneTime": scene_time,
                    "beatTime": beat_time,
                    "stepTime": step_time,
                    "sub": show_sub,
                    "totalProgress": min(1.0, t_sec / total_dur),
                }
                page.evaluate("(p) => window.seekToState(p)", payload)
                jpg = page.screenshot(type="jpeg", quality=95)
                proc.stdin.write(jpg)
                rendered_count += 1
                last_cache_key = cache_key
                last_jpg = jpg

        browser.close()

    proc.stdin.close()
    stderr = proc.stderr.read().decode("utf-8", "ignore")
    rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"ffmpeg failed for EP {episode.ep_num}: {stderr}")

    elapsed = time.time() - t_start
    size_mb = os.path.getsize(out_mp4) / (1024 * 1024)
    print(
        f"[EP {episode.ep_num}] DONE {out_mp4} ({size_mb:.1f} MB, {total_dur:.1f}s, "
        f"rendered {rendered_count}/{total_frames} frames in {elapsed:.1f}s)",
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

"""Time two visually identical 1080p60 exports. Run manually with the renderer's dependencies.

uv run --with playwright --with edge-tts --with imageio-ffmpeg python doc-to-video-course/tests/benchmark_compositing.py
"""
import argparse
import os
import platform
import shutil
import statistics
import subprocess
import sys
import time
import wave
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from playwright.sync_api import Page, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import video_engine as engine
from browser_runtime import launch_chromium


def episode(kind):
    markup = '<canvas class="mg-stage" width="1920" height="1080"></canvas>'
    if kind == "hidden":
        markup += "<span hidden></span>"
    paint = """
const c = ctx.sceneEl.querySelector('canvas').getContext('2d');
mgClear(c);
mgNode(c, 480 + 520 * easeInOut(ctx.p), 480, 240, 100, '移动', '', {state: 'green'});
"""
    beat = engine.Beat("旁白", continuous=True, pause_after=0.55)
    scene = engine.Scene("measure", "", markup, [beat], js_frame=paint, clean_stage=True)
    return engine.Episode("B", "移动", "", "green-card.mp4", [scene])


def prepare_assets(root):
    # Keep the public export path intact, using a local three-second recording.
    # This scene has no math and its rendering should not require a CDN.
    key = engine._tts_cache_key(engine.DEFAULT_VOICE, engine.DEFAULT_RATE, "旁白")
    take = root / "audio_cache" / key
    take.mkdir(parents=True)
    with wave.open(str(take / "audio.wav"), "wb") as wav:
        wav.setparams((2, 2, 48000, 0, "NONE", ""))
        wav.writeframes(bytes(3 * 48000 * 2 * 2))
    katex = root / "katex"
    katex.mkdir()
    (katex / "katex.min.css").touch()
    (katex / "katex.min.js").touch()
    (katex / "auto-render.min.js").write_text("function renderMathInElement() {}", encoding="utf-8")
    return katex


def render(kind, directory):
    shots = 0
    screenshot = Page.screenshot

    def counted(page, *args, **kwargs):
        nonlocal shots
        shots += 1
        return screenshot(page, *args, **kwargs)

    spec = episode(kind)
    with patch.object(Page, "screenshot", counted):
        start = time.perf_counter()
        result = engine.render_episode(spec, str(directory), fps=60)
        seconds = time.perf_counter() - start
    print(f"{directory.name}: {seconds:.3f} s, {shots} browser screenshots", flush=True)
    return seconds, Path(result["mp4"])


def frame_hashes(video):
    # Compare decoded RGB pixels at every timestamp, independent of MP4 metadata.
    cmd = [engine.FFMPEG, "-v", "error", "-i", str(video), "-map", "0:v:0", "-pix_fmt", "rgb24",
           "-f", "framemd5", "-"]
    output = subprocess.run(cmd, capture_output=True, check=True, text=True).stdout
    return [line for line in output.splitlines() if not line.startswith("#")]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep-video", type=Path, help="Save the final green-card MP4 at this path")
    args = parser.parse_args()
    with sync_playwright() as pw:
        browser = launch_chromium(pw)
        print(f"{platform.platform()}, Chromium {browser.version}, 1920×1080 at 60 fps", flush=True)
        browser.close()
    with TemporaryDirectory(prefix="course-compositing-") as directory:
        root = Path(directory)
        katex = prepare_assets(root)
        durations = {"canvas": [], "hidden": []}
        videos = []
        with patch.dict(os.environ, {"D2V_CACHE_DIR": str(root)}), patch.object(engine, "ensure_katex", return_value=str(katex)):
            for i, kind in enumerate(("canvas", "hidden", "hidden", "canvas"), 1):
                seconds, video = render(kind, root / f"{i}-{kind}")
                durations[kind].append(seconds)
                videos.append(video)

        for kind, values in durations.items():
            print(f"{kind} mean: {statistics.mean(values):.3f} s")
        reference = frame_hashes(videos[0])
        for video in videos:
            frames = frame_hashes(video)
            if len(frames) != 213:
                raise ValueError(f"{video.parent.name} has {len(frames)} decoded frames, expected 213")
            matches = sum(a == b for a, b in zip(frames, reference))
            print(f"{video.parent.name}: {matches}/213 frames match the first render exactly")
        if args.keep_video:
            args.keep_video.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(videos[-1], args.keep_video)
            print(f"Saved {args.keep_video}")


if __name__ == "__main__":
    main()

"""Compare decoded export frames with the exact Chromium page used for preflight."""
import subprocess
import sys
import unittest
import wave
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from playwright.sync_api import Page, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from browser_runtime import launch_chromium
import video_engine as engine


FPS = 6
WIDTH, HEIGHT = 480, 270  # Downsample both images identically before comparing.
CANVAS = '<canvas class="mg-stage" width="1920" height="1080" {}></canvas>'
PAINT = """
const stage = ctx.sceneEl.querySelector("canvas");
const pen = stage.getContext("2d");
pen.clearRect(0, 0, 1920, 1080);
pen.fillStyle = "#de382a";
pen.fillRect(600, 420, 180, 160);
"""
LONG_SUB = "先记录刚读到的词，再把查询移到下一行。" * 10
BEHIND_SUBTITLE = """
const x = 540 + ctx.p * 550;
for (let i = 0; i < 12; i++) {
  // Luminance contrast survives 4:2:0 color subsampling in both export paths.
  pen.fillStyle = i % 2 ? "#363c3e" : "#d7d5d1";
  pen.fillRect(x + 18 * i, 960, 18, 108);
}
"""


def course_fixture():
    overlay = ('<i hidden style="position:fixed;left:860px;top:420px;width:160px;'
               'height:160px;background:#096742;z-index:4"></i>')
    specs = [
        ("opacity", CANVAS.format(""), "stage.style.opacity = ctx.p;", [""]),
        ("transform", CANVAS.format(""),
         'stage.style.transform = "translateX(" + 200 * ctx.p + "px)";', [LONG_SUB]),
        ("step", CANVAS.format('data-step="1"'), "", ["", ""]),
        ("overlay", CANVAS.format("") + overlay,
         'ctx.sceneEl.querySelector("i").hidden = ctx.beatIdx === 0;', ["", ""]),
        ("hidden", CANVAS.format("") + "<span hidden>author note</span>", "", [LONG_SUB]),
        ("crossing", CANVAS.format(""), BEHIND_SUBTITLE, ["色带从字幕底下经过。"]),
    ]
    scenes = []
    timeline = []
    for i, (name, markup, behavior, subs) in enumerate(specs):
        scenes.append(engine.Scene(name, name, markup, [engine.Beat(s, continuous=True) for s in subs],
                                   js_frame=PAINT + behavior, clean_stage=True))
        for j, sub in enumerate(subs):
            start = len(timeline)
            timeline.append(dict(scene_idx=i, scene_id=name, global_idx=start, beat_idx=j,
                                 sub=sub, cue={"step": j}, marks={}, start_sec=start,
                                 step_start_sec=start, speech_end_sec=start + 1, end_sec=start + 1,
                                 continuous=True, anim_settle_sec=engine.DOM_ENTER_SEC))
    return engine.Episode("01", "", "", "comparison.mp4", scenes), timeline


def decode(input_args):
    cmd = [engine.FFMPEG, "-v", "error", *input_args, "-an", "-vf", f"scale={WIDTH}:{HEIGHT}:flags=area",
           "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    frame_size = WIDTH * HEIGHT * 3
    return [raw[i:i + frame_size] for i in range(0, len(raw), frame_size)]


def pixels(frame, rect):
    x1, y1, x2, y2 = rect
    for y in range(y1, y2):
        yield from frame[3 * (y * WIDTH + x1):3 * (y * WIDTH + x2)]


def subtitle_ink(image):
    data = bytes(pixels(image, (30, 180, 450, 263)))
    return {j for j in range(0, len(data), 3) if max(data[j:j + 3]) < 155}


@contextmanager
def count_captures():
    original = Page.screenshot
    counts = Counter()

    def record(page, *args, **kwargs):
        active = page.evaluate("document.querySelector('main > .active')?.id")
        counts[active, "clip" if "clip" in kwargs else "page"] += 1
        return original(page, *args, **kwargs)

    with patch.object(Page, "screenshot", record):
        yield counts


class CompositingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        episode, timeline = course_fixture()
        cls.entries = engine._build_frame_entries(timeline, timeline[-1]["end_sec"], FPS)
        work = TemporaryDirectory()
        cls.addClassCleanup(work.cleanup)
        directory = work.name
        root = Path(directory)
        html = str(root / "episode.html")
        # Nothing in these scenes uses math or speech. Keep rendering offline.
        (root / "auto-render.min.js").write_text("function renderMathInElement() {}")
        (root / "katex.min.js").touch()
        (root / "katex.min.css").touch()
        with patch.object(engine, "ensure_katex", return_value=directory):
            engine.build_episode_html(episode, html, timeline=timeline)
        wav = str(root / "silence.wav")
        with wave.open(wav, "wb") as audio:
            audio.setparams((1, 2, 48000, 0, "NONE", ""))
            audio.writeframes(bytes(2 * 48000 * timeline[-1]["end_sec"]))

        with sync_playwright() as pw:
            try:
                browser = launch_chromium(pw)
            except FileNotFoundError as error:
                raise unittest.SkipTest(str(error)) from error
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            page.goto(Path(html).as_uri())
            page.evaluate("document.fonts.ready")
            # Capture the page natively, independently of either export compositor.
            cls.png_stream = str(root / "native.pngs")
            with open(cls.png_stream, "wb") as images:
                for entry in cls.entries:
                    page.evaluate("window.seekToState", entry["payload"])
                    images.write(page.screenshot())
            browser.close()
        cls.reference = decode(["-f", "image2pipe", "-framerate", str(FPS), "-i", cls.png_stream])

        cls.episode, cls.root, cls.html, cls.wav = episode, root, html, wav

    @classmethod
    def webcodecs_frames(cls):
        # The PNG backend can be tested independently of encoder availability and errors.
        if not hasattr(cls, "fast"):
            fast = str(cls.root / "webcodecs.mp4")
            with count_captures() as cls.fast_counts:
                supported, _ = engine._render_via_webcodecs(
                    cls.episode, str(cls.root), cls.html, str(cls.root), cls.wav, fast, cls.entries, FPS, "veryfast")
            cls.fast = decode(["-i", fast]) if supported else None

        if cls.fast is None:
            raise unittest.SkipTest("Chromium does not support a WebCodecs encoder for this fixture")
        return cls.fast

    def check_full_resolution(self, output):
        # Compare all three YUV planes at 1920×1080 for every timestamp, including
        # areas outside the focused pixel checks. Use codec tolerance, not a golden PNG.
        cmd = [engine.FFMPEG, "-v", "error", "-i", str(output), "-f", "image2pipe",
               "-framerate", str(FPS), "-i", self.png_stream, "-filter_complex",
               "[1:v]format=yuv420p[ref];[0:v][ref]psnr=stats_file=-:shortest=1",
               "-an", "-f", "null", "-"]
        stats = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.splitlines()
        self.assertEqual(len(stats), len(self.entries))
        for i, line in enumerate(stats):
            values = dict(field.split(":", 1) for field in line.split())
            with self.subTest(frame=i, region="full 1080p frame"):
                self.assertGreater(float(values["psnr_avg"]), 38.0)

    def check_frame_pixels(self, frames):
        self.assertEqual(len(frames), len(self.entries))
        self.assertEqual(len(self.reference), len(self.entries))
        for i, (entry, expected, actual) in enumerate(zip(self.entries, self.reference, frames)):
            scene = entry["payload"]["sceneId"]
            # Include color interiors plus edges where the CSS transform moves the subject.
            rects = [(145, 100, 253, 147), (410, 5, 428, 22), (28, 237, 45, 248)]
            if scene == "crossing":
                # Covers the caption text, rounded ends, blur and the moving stripes beyond them.
                rects.extend([(168, 242, 326, 267), (218, 252, 259, 260)])
            for rect in rects:
                with self.subTest(scene=scene, frame=i, region=rect):
                    ref, out = bytes(pixels(expected, rect)), bytes(pixels(actual, rect))
                    mean_error = sum(abs(a - b) for a, b in zip(ref, out)) / len(ref)
                    self.assertLess(mean_error, 3.5)
            if entry["payload"]["sub"] == LONG_SUB and i % FPS == FPS - 1:
                # Text-mask overlap detects a different line break, typeface, or missing line.
                ref, out = subtitle_ink(expected), subtitle_ink(actual)
                with self.subTest(scene=scene, frame=i, region="long subtitle"):
                    self.assertGreater(len(ref), 150)
                    self.assertGreater(len(ref & out) / len(ref | out), 0.90)

    def test_png_fallback_matches_preflight(self):
        output = str(self.root / "png.mp4")
        with count_captures() as counts:
            engine._render_via_screenshots(self.episode, self.html, self.wav, output, self.entries, FPS, "veryfast")
        self.check_frame_pixels(decode(["-i", output]))
        self.check_full_resolution(output)
        self.assertLessEqual(counts["scene-hidden", "page"] + counts["scene-hidden", "clip"], 3)
        self.assertLessEqual(counts["scene-crossing", "page"], 3)

    def test_webcodecs_matches_preflight(self):
        self.check_frame_pixels(self.webcodecs_frames())
        self.check_full_resolution(self.root / "webcodecs.mp4")

    def test_hidden_sibling_preserves_fast_canvas(self):
        self.webcodecs_frames()
        # A compositor can capture a backdrop and a subtitle plate once each.
        self.assertLessEqual(self.fast_counts["scene-hidden", "page"] + self.fast_counts["scene-hidden", "clip"], 3)

    def test_subtitle_overlap_preserves_fast_canvas(self):
        self.webcodecs_frames()
        # The moving portion can be captured locally without repainting the full page.
        self.assertLessEqual(self.fast_counts["scene-crossing", "page"], 3)


if __name__ == "__main__":
    unittest.main()

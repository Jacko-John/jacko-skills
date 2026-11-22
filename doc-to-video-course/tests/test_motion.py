"""Regression checks for motion across sentence boundaries and its narration clock."""
import asyncio
import json
import sys
import unittest
import wave
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import video_engine as engine


class MotionTests(unittest.TestCase):
    def test_legacy_wav_and_new_word_boundaries_use_the_same_recording(self):
        text = "draw"
        key = engine._tts_cache_key("voice", "-3%", text)

        def write_wav(path, frames):
            with wave.open(str(path), "wb") as audio:
                audio.setparams((2, 2, 48000, 0, "NONE", ""))
                audio.writeframes(bytes(frames * 4))

        async def record(text, voice, rate, need_words, mp3, staging):
            write_wav(staging / "audio.wav", 4800)
            (staging / "words.json").write_text(json.dumps([{"t": 0.02, "text": text}]))

        with TemporaryDirectory() as work:
            root = Path(work)
            write_wav(root / (key + ".wav"), 9600)

            async def fetch(require_words):
                return await engine._synth_one(
                    asyncio.Semaphore(1), text, str(root / "beat.wav"), work,
                    "voice", "-3%", need_words=require_words,
                )

            with patch.object(engine, "_synthesize_take", side_effect=record) as recorder:
                self.assertEqual(asyncio.run(fetch(False)), (0.2, []))
                with_words = asyncio.run(fetch(True))
                self.assertEqual(with_words, (0.1, [{"t": 0.02, "text": text}]))
                self.assertEqual(asyncio.run(fetch(False)), with_words)
                recorder.assert_awaited_once()

    def test_motion_survives_the_pause_and_next_sentence(self):
        scene = engine.Scene(
            "drawer", "", '<canvas class="mg-stage"></canvas>',
            [engine.Beat("move"), engine.Beat("hold")],
            js_frame="""window.position = ctx.motion(0, "start", 1.2);
                        window.result = ctx.motion(1, "result", null);
                        window.snapVal = ctx.snap(1, "result", 0.25);""",
        )
        episode = engine.Episode("01", "Test", "", "test.mp4", [scene])
        timeline = [
            dict(scene_idx=0, scene_id="drawer", global_idx=i, beat_idx=i, sub="",
                 cue={}, marks=marks, start_sec=float(i), step_start_sec=float(i),
                 speech_end_sec=i + 0.8, end_sec=i + 1, continuous=True,
                 anim_settle_sec=engine.DOM_ENTER_SEC)
            for i, marks in enumerate([{"start": 0.0}, {"result": 0.4}])
        ]
        fps = 60
        frames = engine._build_frame_entries(timeline, 2.0, fps)
        with TemporaryDirectory() as work, sync_playwright() as playwright:
            page_path = Path(work) / "episode.html"
            # This scene uses no math. Avoid fetching external assets in this test.
            (Path(work) / "auto-render.min.js").write_text("function renderMathInElement() {}")
            with patch.object(engine, "ensure_katex", return_value=work):
                engine.build_episode_html(episode, str(page_path), timeline=timeline)
            browser = engine.launch_chromium(playwright)
            page = browser.new_page()
            page.goto(page_path.as_uri())
            # Jump backwards, then cross the sentence boundary one frame at a time.
            for index in (119, 0, 50, 59, 60, 61, 83, 84, 105, 119):
                entry = frames[index]
                page.evaluate("window.seekToState", entry["payload"])
                position, result, snap_val = page.evaluate("[window.position, window.result, window.snapVal]")
                t = (index + 0.5) / fps
                self.assertAlmostEqual(position, min(t / 1.2, 1.0))
                self.assertAlmostEqual(result, max(0.0, min((t - 1.4) / 0.4, 1.0)))
                self.assertAlmostEqual(snap_val, max(0.0, min((t - 1.4) / 0.25, 1.0)))
                self.assertIsNone(entry["cache_key"])
            browser.close()


if __name__ == "__main__":
    unittest.main()

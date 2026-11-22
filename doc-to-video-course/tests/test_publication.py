"""Offline regressions for publishing complete episodes and course manifests."""
import json
import os
import sys
import unittest
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_runner as runner
import video_engine as engine


class PublicationTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.specs = self.root / "specs"
        self.out = self.root / "videos"
        self.specs.mkdir()
        self.out.mkdir()
        self.cache = self.root / "cache"
        self.enter_patch(patch.dict(os.environ, D2V_CACHE_DIR=str(self.cache)))
        take = self.cache / "audio_cache" / engine._tts_cache_key(engine.DEFAULT_VOICE, engine.DEFAULT_RATE, "fixture")
        take.mkdir(parents=True)
        with wave.open(str(take / "audio.wav"), "wb") as wav:
            wav.setparams((2, 2, 48000, 0, "NONE", ""))
            wav.writeframes(bytes(4800 * 4))
        (take / "words.json").write_text("[]")
        self.enter_patch(patch.object(engine, "ensure_katex", return_value=str(self.root)))
        self.workdirs = []

        def encode(ep, work, html, katex, audio, video, frames, fps, preset):
            self.workdirs.append(work)
            subtitle = ep.scenes[0].beats[0].sub
            Path(video).write_text(subtitle)
            if subtitle == "fail":
                raise RuntimeError("injected encode failure")
            return True, len(frames)

        self.enter_patch(patch.object(engine, "_render_via_webcodecs", side_effect=encode))

    def enter_patch(self, patcher):
        self.addCleanup(patcher.stop)
        return patcher.start()

    def spec(self, number, subtitle):
        (self.specs / f"ep{number}.py").write_text(
            "from video_engine import Beat, Scene, Episode\n"
            "def build_episode():\n"
            f"    beat = Beat({subtitle!r}, tts='fixture')\n"
            f"    return Episode({number!r}, '', '', '{number}.mp4', [Scene('s', '', '', [beat])])\n"
        )

    def build(self, *args):
        argv = ["build_runner.py", "--spec-dir", str(self.specs), "--out-dir", str(self.out), "--workers", "1", *args]
        with patch.object(sys, "argv", argv):
            runner.main()

    def manifest(self):
        return json.loads((self.out / "manifest.json").read_text())

    def artifacts(self):
        return {file.name: file.read_bytes() for file in self.out.glob("*") if file.suffix in {".mp4", ".srt", ".json"}}

    def test_partial_updates_preserve_other_rows_and_full_rebuild_drops_removed_specs(self):
        self.spec("01", "first")
        self.spec("02", "second")
        self.build()
        first = self.manifest()[0]
        self.spec("02", "modified second")
        self.build("--eps", "2")
        self.assertEqual([row["ep_num"] for row in self.manifest()], ["01", "02"])
        self.assertEqual(self.manifest()[0], first)
        self.assertEqual((self.out / "02.mp4").read_text(), "modified second")
        (self.specs / "ep01.py").unlink()
        self.build()
        self.assertEqual([row["ep_num"] for row in self.manifest()], ["02"])

    def test_failed_batch_and_direct_render_leave_published_files_intact(self):
        self.spec("01", "first")
        self.spec("02", "second")
        self.build()
        before = self.artifacts()
        self.spec("01", "updated first")
        self.spec("02", "fail")
        with self.assertRaisesRegex(RuntimeError, "encode failure"):
            self.build()
        self.assertEqual(self.artifacts(), before)
        ep = runner._load_one(str(self.specs / "ep02.py"), str(self.specs))
        with self.assertRaisesRegex(RuntimeError, "encode failure"):
            engine.render_episode(ep, str(self.out))
        self.assertEqual(self.artifacts(), before)
        self.assertEqual(len(set(self.workdirs)), len(self.workdirs))
        self.assertFalse(any(Path(d).exists() for d in self.workdirs))

    def test_failed_manifest_replacement_restores_overwritten_and_removes_new_files(self):
        self.spec("01", "initial")
        self.build()
        before = self.artifacts()
        self.spec("01", "replacement")
        self.spec("02", "brand new")
        replace_file = os.replace

        def fail_manifest(staged, target):
            if target == self.out / "manifest.json":
                raise PermissionError("injected publication failure")
            replace_file(staged, target)

        with patch.object(os, "replace", side_effect=fail_manifest):
            with self.assertRaisesRegex(PermissionError, "publication failure"):
                self.build()
        self.assertEqual(self.artifacts(), before)

    def test_windows_lock_targets_the_first_byte_of_a_stable_file(self):
        def check_lock(fd, flag, count):
            self.assertEqual((os.fstat(fd).st_size, os.lseek(fd, 0, os.SEEK_CUR), count), (1, 0, 1))
        crt = SimpleNamespace(LK_LOCK=1, locking=Mock(side_effect=check_lock))
        with patch.object(engine, "os", SimpleNamespace(name="nt", SEEK_END=os.SEEK_END)):
            with patch.dict(sys.modules, msvcrt=crt):
                for _ in range(2):
                    with engine.publication_lock(self.out):
                        self.assertTrue((self.out / ".course-publish.lock").is_file())
        self.assertEqual(crt.locking.call_count, 2)

    def test_concurrent_partial_publications_keep_both_episodes(self):
        def publish(number):
            with TemporaryDirectory(dir=self.out) as stage:
                folder = Path(stage)
                doc = {"ep_num": number, "duration_sec": 1.0}
                for key in ("mp4", "srt"):
                    src = folder / f"episode.{key}"
                    src.write_text(number)
                    doc[key] = str(src)
                runner._publish_batch([(doc, f"{number}.mp4")], self.out, folder, True, None, None)

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(publish, ["01", "02"]))
        self.assertEqual([row["ep_num"] for row in self.manifest()], ["01", "02"])
        for row in self.manifest():
            self.assertEqual(Path(row["mp4"]).read_text(), row["ep_num"])


if __name__ == "__main__":
    unittest.main()

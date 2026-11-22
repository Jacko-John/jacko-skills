"""Browser selection on machines with different Playwright installations."""
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, call, patch

from playwright.sync_api import Error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import browser_runtime as runtime


class BrowserRuntimeTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"D2V_CHROME_EXE": ""})
        env.start()
        self.addCleanup(env.stop)
        self.playwright = Mock()
        self.chromium = self.playwright.chromium

    def test_default_uses_playwright_managed_shell(self):
        self.assertIs(runtime.launch_chromium(self.playwright), self.chromium.launch.return_value)
        self.chromium.launch.assert_called_once_with()

    def test_full_bundle_works_without_a_separate_shell(self):
        with TemporaryDirectory() as work:
            exe = Path(work) / "chrome"
            exe.touch()
            self.chromium.executable_path = str(exe)
            browser = object()
            self.chromium.launch.side_effect = [Error("Executable doesn't exist"), browser]
            self.assertIs(runtime.launch_chromium(self.playwright), browser)
            self.assertEqual(self.chromium.launch.call_args_list, [call(), call(executable_path=exe)])

    def test_explicit_path_takes_precedence(self):
        with TemporaryDirectory() as work:
            exe = Path(work) / "custom chrome.exe"
            exe.touch()
            with patch.dict(os.environ, {"D2V_CHROME_EXE": str(exe)}):
                runtime.launch_chromium(self.playwright)
            self.chromium.launch.assert_called_once_with(executable_path=exe)

    def test_missing_installation_offers_uv_command(self):
        with TemporaryDirectory() as work, patch.object(runtime.shutil, "which", return_value=None):
            self.chromium.executable_path = str(Path(work) / "missing")
            self.chromium.launch.side_effect = [
                Error("Executable doesn't exist"),
                Error("Chromium distribution 'chrome' is not found"),
            ]
            with self.assertRaisesRegex(FileNotFoundError, "uv run --with playwright"):
                runtime.launch_chromium(self.playwright)

    def test_launch_failure_preserves_browser_diagnostic(self):
        self.chromium.launch.side_effect = Error("Host system is missing dependencies")
        with self.assertRaisesRegex(Error, "missing dependencies"):
            runtime.launch_chromium(self.playwright)
        self.chromium.launch.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()

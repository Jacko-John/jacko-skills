"""Launch Chromium for validation and export using the active Playwright installation."""
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from playwright.sync_api import Browser, Error, Playwright, sync_playwright


def _launch(playwright: Playwright, **options) -> Browser:
    chromium = playwright.chromium
    override = os.environ.get("D2V_CHROME_EXE")
    if override:
        executable = Path(override).expanduser()
        if not executable.is_file():
            raise FileNotFoundError(f"D2V_CHROME_EXE points to a missing file: {executable}")
        return chromium.launch(executable_path=executable, **options)

    # Let the driver resolve the matching headless shell (including a custom
    # PLAYWRIGHT_BROWSERS_PATH). An installation made with --no-shell has only
    # the full executable. Report real launch failures such as missing libraries.
    try:
        return chromium.launch(**options)
    except Error as exc:
        if "executable doesn't exist" not in str(exc).lower():
            raise
    bundled = Path(chromium.executable_path)
    if bundled.is_file():
        return chromium.launch(executable_path=bundled, **options)

    for name in ("chromium", "chromium-browser", "google-chrome", "chrome"):
        executable = shutil.which(name)
        if executable:
            return chromium.launch(executable_path=executable, **options)
    try:
        # The chrome channel knows system installation paths on Windows and macOS.
        return chromium.launch(channel="chrome", **options)
    except Error as exc:
        message = str(exc).lower()
        if "is not found" not in message and "executable doesn't exist" not in message:
            raise
        raise FileNotFoundError(
            "Install Chromium using 'uv run --with playwright playwright install chromium' "
            "or set D2V_CHROME_EXE to the browser executable."
        ) from exc


def launch_chromium(playwright: Playwright) -> Browser:
    """Open a headless browser for the caller's active Playwright session."""
    return _launch(playwright)


def find_chrome_exe() -> str:
    """Return the selected executable for legacy callers that launch Chromium themselves."""
    def probe() -> str:
        with sync_playwright() as playwright:
            # CDP exposes the actual executable even for --only-shell installs.
            browser = _launch(playwright, args=["--enable-automation"])
            try:
                session = browser.new_browser_cdp_session()
                return session.send("Browser.getBrowserCommandLine")["arguments"][0]
            finally:
                browser.close()

    # Older callers can ask for the path inside a running sync Playwright session.
    # Its asyncio loop lives on their thread.
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(probe).result()

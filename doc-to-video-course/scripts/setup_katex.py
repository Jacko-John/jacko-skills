"""Download and cache KaTeX CSS, JS, and woff2 fonts locally for offline 1080p video rendering."""
import argparse
import os
import re
import urllib.request
from typing import Optional

KATEX_VERSION = "0.16.11"
BASE_URL = f"https://cdn.jsdelivr.net/npm/katex@{KATEX_VERSION}/dist"
DEFAULT_CACHE = os.path.expanduser("~/.cache/doc-to-video-course")


def ensure_katex(katex_dir: Optional[str] = None) -> str:
    target = katex_dir or os.path.join(
        os.environ.get("D2V_CACHE_DIR", DEFAULT_CACHE), "katex"
    )
    fonts_dir = os.path.join(target, "fonts")
    css_path = os.path.join(target, "katex.min.css")
    js_path = os.path.join(target, "katex.min.js")
    auto_path = os.path.join(target, "auto-render.min.js")

    if (
        os.path.exists(css_path)
        and os.path.exists(js_path)
        and os.path.exists(auto_path)
        and os.path.isdir(fonts_dir)
        and len(os.listdir(fonts_dir)) >= 15
    ):
        return target

    os.makedirs(fonts_dir, exist_ok=True)
    urllib.request.urlretrieve(f"{BASE_URL}/katex.min.css", css_path)
    urllib.request.urlretrieve(f"{BASE_URL}/katex.min.js", js_path)
    urllib.request.urlretrieve(f"{BASE_URL}/contrib/auto-render.min.js", auto_path)

    with open(css_path, "r", encoding="utf-8") as f:
        css = f.read()
    fonts = sorted(set(re.findall(r"fonts/[a-zA-Z0-9_.-]+\.woff2", css)))
    for rel in fonts:
        dst = os.path.join(target, rel)
        if not os.path.exists(dst):
            urllib.request.urlretrieve(f"{BASE_URL}/{rel}", dst)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default=None, help="Target KaTeX cache directory")
    args = parser.parse_args()
    out = ensure_katex(args.dir)
    print(f"KaTeX ready at: {out}")

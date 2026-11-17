"""Fast Chromium pre-render check for episode specs: JS errors, KaTeX dollars, and bounding-box overflow."""
import argparse
import glob
import importlib.util
import os
import sys
import warnings

from playwright.sync_api import sync_playwright

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from video_engine import Episode, build_episode_html, find_chrome_exe, get_cache_root


def load_episodes_from_dir(spec_dir: str, pattern: str = "ep*.py") -> list[Episode]:
    sys.path.insert(0, spec_dir)
    episodes: list[Episode] = []
    for path in sorted(glob.glob(os.path.join(spec_dir, pattern))):
        mod_name = os.path.splitext(os.path.basename(path))[0]
        spec = importlib.util.spec_from_file_location(mod_name, path)
        mod = importlib.util.module_from_spec(spec)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", SyntaxWarning)
            spec.loader.exec_module(mod)
            for w in caught:
                print(f"[SYNTAX WARN] {path}:{w.lineno}: {w.message}")
        builder = None
        if hasattr(mod, "build_episode"):
            builder = mod.build_episode
        else:
            for attr in dir(mod):
                if attr.startswith("build_ep") and callable(getattr(mod, attr)):
                    builder = getattr(mod, attr)
                    break
        if builder is None:
            raise ValueError(f"No build_episode() or build_ep*() found in {path}")
        episodes.append(builder())
    return episodes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec-dir", required=True, help="Directory containing ep*.py files")
    parser.add_argument("--pattern", default="ep*.py")
    parser.add_argument("--sample-dir", default=None, help="Optional dir to save sample JPGs")
    parser.add_argument("--max-bottom", type=float, default=968.0)
    args = parser.parse_args()

    episodes = load_episodes_from_dir(args.spec_dir, args.pattern)
    if not episodes:
        raise SystemExit(f"No episodes matched {args.pattern} in {args.spec_dir}")

    tmp_html_dir = os.path.join(get_cache_root(), "validate_html")
    os.makedirs(tmp_html_dir, exist_ok=True)
    if args.sample_dir:
        os.makedirs(args.sample_dir, exist_ok=True)

    exe = find_chrome_exe()
    page_errors: list[str] = []
    overflows: list[str] = []
    dollar_leaks: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=exe)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.on("pageerror", lambda err: page_errors.append(str(err)))

        for ep in episodes:
            hp = os.path.join(tmp_html_dir, f"ep_{ep.ep_num}.html")
            build_episode_html(ep, hp)
            page.goto("file://" + hp, wait_until="load")
            page.evaluate("document.fonts.ready")

            raw_dollars = page.evaluate("() => document.body.innerText.includes('$$')")
            if raw_dollars:
                dollar_leaks.append(f"EP {ep.ep_num}")

            for si, sc in enumerate(ep.scenes):
                if not sc.beats:
                    overflows.append(f"EP {ep.ep_num} {sc.scene_id}: empty beats")
                    continue
                for bi in sorted({0, len(sc.beats) - 1}):
                    bt = sc.beats[bi]
                    page.evaluate(
                        "(p) => window.seekToState(p)",
                        {
                            "sceneIdx": si,
                            "sceneId": sc.scene_id,
                            "beatIdx": bi,
                            "cue": bt.cue,
                            "p": 0.72,
                            "sceneTime": 2.5,
                            "beatTime": 1.0,
                            "stepTime": 1.0,
                            "sub": bt.sub,
                            "totalProgress": (si + 0.5) / max(1, len(ep.scenes)),
                        },
                    )
                    ov = page.evaluate(
                        """() => {
                          const st = document.querySelector('.stage');
                          const sc = document.querySelector('.scene.active');
                          let maxBottom = 0;
                          for (const k of sc.querySelectorAll('.card, .glass-panel, .svg-card, .code-window, .math-stage, .callout, pre, table, svg')) {
                            const r = k.getBoundingClientRect();
                            if (r.height > 0 && parseFloat(getComputedStyle(k).opacity) > 0.01) {
                              maxBottom = Math.max(maxBottom, r.bottom);
                            }
                          }
                          const svgIssues = [];
                          sc.querySelectorAll('svg').forEach((svg, idx) => {
                            const sRect = svg.getBoundingClientRect();
                            if (sRect.width === 0 || parseFloat(getComputedStyle(svg).opacity) <= 0.01) return;
                            const texts = Array.from(svg.querySelectorAll('text')).map(t => ({
                              node: t,
                              text: t.textContent.trim(),
                              r: t.getBoundingClientRect(),
                              op: parseFloat(getComputedStyle(t).opacity)
                            })).filter(x => x.r.width > 0 && x.op > 0.05);
                            for (let i = 0; i < texts.length; i++) {
                              const a = texts[i];
                              if (a.r.left < sRect.left - 8 || a.r.right > sRect.right + 8 || a.r.top < sRect.top - 8 || a.r.bottom > sRect.bottom + 8) {
                                svgIssues.push('SVG#' + idx + ' text out of bounds: ' + a.text);
                              }
                              for (let j = i + 1; j < texts.length; j++) {
                                const b = texts[j];
                                const ix = Math.max(0, Math.min(a.r.right, b.r.right) - Math.max(a.r.left, b.r.left));
                                const iy = Math.max(0, Math.min(a.r.bottom, b.r.bottom) - Math.max(a.r.top, b.r.top));
                                if (ix > 4 && iy > 3) {
                                  svgIssues.push('SVG#' + idx + ' text overlap: \"' + a.text + '\" vs \"' + b.text + '\"');
                                }
                              }
                            }
                            // Check if any large container rect overlaps an earlier visible text node
                            const children = Array.from(svg.children);
                            for (let ci = 0; ci < children.length; ci++) {
                              const ch = children[ci];
                              if (ch.tagName.toLowerCase() !== 'rect') continue;
                              const rr = ch.getBoundingClientRect();
                              if (rr.width < 120 || rr.height < 80 || parseFloat(getComputedStyle(ch).opacity) <= 0.05) continue;
                              for (const t of texts) {
                                const tIdx = children.indexOf(t.node);
                                if (tIdx >= 0 && tIdx < ci) {
                                  const ix = Math.max(0, Math.min(rr.right, t.r.right) - Math.max(rr.left, t.r.left));
                                  const iy = Math.max(0, Math.min(rr.bottom, t.r.bottom) - Math.max(rr.top, t.r.top));
                                  if (ix > 6 && iy > 4) {
                                    svgIssues.push('SVG#' + idx + ' later rect covers earlier text: ' + t.text);
                                  }
                                }
                              }
                            }
                          });
                          return { scrollH: st.scrollHeight, clientH: st.clientHeight, maxBottom, svgIssues };
                        }"""
                    )
                    if ov["scrollH"] > ov["clientH"] + 2 or ov["maxBottom"] > args.max_bottom:
                        overflows.append(
                            f"EP {ep.ep_num} {sc.scene_id} beat {bi}: {ov}"
                        )
                    for si_msg in ov.get("svgIssues", []):
                        overflows.append(f"EP {ep.ep_num} {sc.scene_id} beat {bi}: {si_msg}")
                if args.sample_dir:
                    page.screenshot(
                        path=os.path.join(
                            args.sample_dir, f"ep_{ep.ep_num}_{sc.scene_id}.jpg"
                        ),
                        type="jpeg",
                        quality=88,
                    )
            print(
                f"[OK] EP {ep.ep_num}: {len(ep.scenes)} scenes, {sum(len(s.beats) for s in ep.scenes)} beats checked"
            )
        browser.close()

    if page_errors or overflows or dollar_leaks:
        print("VALIDATION FAILED:")
        if page_errors:
            print("  JS PageErrors:", page_errors)
        if dollar_leaks:
            print("  Unrendered KaTeX $$:", dollar_leaks)
        if overflows:
            for o in overflows:
                print("  Overflow:", o)
        raise SystemExit(1)

    print("ALL SCENES PASSED VALIDATION (0 JS errors, 0 KaTeX leaks, 0 overflows).")


if __name__ == "__main__":
    main()

"""Check DOM/SVG layout and JavaScript at export frames sampled from the narration timeline."""
import argparse
import asyncio
import glob
import importlib.util
import os
import sys
import warnings
from bisect import bisect_left
from collections import defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import sync_playwright

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from browser_runtime import launch_chromium
from video_engine import (
    DEFAULT_RATE,
    DEFAULT_VOICE,
    FPS,
    Episode,
    _build_frame_entries,
    build_episode_html,
    get_cache_root,
    synth_all_beats,
)


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


def sample_frames(timeline: list[dict], fps: int) -> dict:
    """Group real export payloads around beat changes and word onsets, with an interior sample."""
    selected = defaultdict(list)
    if not timeline:
        return selected
    frames = _build_frame_entries(timeline, timeline[-1]["end_sec"], fps)
    # Export evaluates state at the center of each encoded frame. Match its comparison
    # exactly even when a spoken boundary falls halfway through a frame.
    centers = [(i + 0.5) / fps for i in range(len(frames))]
    probes = set()
    for item in timeline:
        start = item["start_sec"]
        speech_duration = item["speech_end_sec"] - start
        boundaries = [start, item["speech_end_sec"], item["end_sec"]]
        boundaries.extend(start + offset for offset in item["marks"].values())
        for timestamp in boundaries:
            after = bisect_left(centers, timestamp)
            probes.update((after - 1, after))
        fractions = (0.12, 0.92) if item["continuous"] else (0.72,)
        for fraction in fractions:
            probes.add(bisect_left(centers, start + fraction * speech_duration))

    for index in sorted(i for i in probes if 0 <= i < len(frames)):
        payload = frames[index]["payload"]
        selected[payload["sceneIdx"], payload["beatIdx"]].append((index, payload))
    return selected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec-dir", required=True, help="Directory containing ep*.py files")
    parser.add_argument("--pattern", default="ep*.py")
    parser.add_argument("--sample-dir", help="Save scene JPGs and sampled frames for visual comparison")
    parser.add_argument("--voice", default=DEFAULT_VOICE)
    parser.add_argument("--rate", default=DEFAULT_RATE)
    parser.add_argument("--fps", type=int, default=FPS, help="Frame rate of the target export")
    parser.add_argument("--max-bottom", type=float, default=968.0)
    args = parser.parse_args()

    if args.fps < 1:
        parser.error("--fps must be positive")

    episodes = load_episodes_from_dir(args.spec_dir, args.pattern)
    if not episodes:
        raise SystemExit(f"No episodes matched {args.pattern} in {args.spec_dir}")

    # Synthesize before starting synchronous Playwright, which owns an asyncio loop.
    # Per-run WAV copies are disposable. Narration and word boundaries use the export cache.
    audio_cache = os.path.join(get_cache_root(), "audio_cache")
    prepared = []
    for ep in episodes:
        with TemporaryDirectory(prefix="course-preflight-audio-") as work_dir:
            timeline = asyncio.run(synth_all_beats(ep, work_dir, audio_cache, args.voice, args.rate))
        prepared.append((ep, timeline, sample_frames(timeline, args.fps)))

    if args.sample_dir:
        os.makedirs(args.sample_dir, exist_ok=True)

    page_errors: list[str] = []
    overflows: list[str] = []
    dollar_leaks: list[str] = []

    with TemporaryDirectory(prefix="course-preflight-html-") as tmp_html_dir, sync_playwright() as p:
        browser = launch_chromium(p)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.on("pageerror", lambda err: page_errors.append(str(err)))

        for ep, timeline, samples in prepared:
            hp = os.path.join(tmp_html_dir, f"ep_{ep.ep_num}.html")
            build_episode_html(ep, hp, timeline=timeline)
            page.goto(Path(hp).resolve().as_uri(), wait_until="load")
            page.evaluate("document.fonts.ready")

            pedagogy_warns: list[str] = []
            for si, sc in enumerate(ep.scenes):
                if not sc.beats:
                    overflows.append(f"EP {ep.ep_num} {sc.scene_id}: empty beats")
                    continue
                if len(sc.beats) > 1 and not any(b.continuous for b in sc.beats):
                    distinct_cues = {repr(sorted(b.cue.items())) for b in sc.beats}
                    if len(distinct_cues) <= 1:
                        pedagogy_warns.append(
                            f"EP {ep.ep_num} {sc.scene_id}: all {len(sc.beats)} beats share identical cue (static slide)"
                        )
                seen_dense_texts: set[str] = set()
                if args.sample_dir:
                    frame_dir = os.path.join(args.sample_dir, f"ep_{ep.ep_num}_{sc.scene_id}")
                    os.makedirs(frame_dir, exist_ok=True)
                for bi in range(len(sc.beats)):
                    for index, payload in samples[si, bi]:
                        page.evaluate("(p) => window.seekToState(p)", payload)
                        if args.sample_dir:
                            page.screenshot(path=os.path.join(frame_dir, f"frame_{index:06d}.jpg"), quality=88)
                        ov = page.evaluate(
                            """() => {
                              const st = document.querySelector('.stage');
                              const sc = document.querySelector('.scene.active');
                              let maxBottom = 0;
                              for (const k of sc.querySelectorAll('.card, .glass-panel, .svg-card, .code-window, .code-spotlight, .math-stage, .float-math, .callout, pre, table, svg')) {
                                const r = k.getBoundingClientRect();
                                if (r.height > 0 && parseFloat(getComputedStyle(k).opacity) > 0.01) {
                                  maxBottom = Math.max(maxBottom, r.bottom);
                                }
                              }
                              const longTexts = [];
                              sc.querySelectorAll('.note-block p, .card p, .callout').forEach((el) => {
                                if (parseFloat(getComputedStyle(el).opacity) > 0.05) {
                                  const txt = el.innerText.replace(/\\s+/g, ' ').trim();
                                  if (txt.length > 85) longTexts.push(txt.slice(0, 40) + '... (' + txt.length + ' chars)');
                                }
                              });
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
                                      svgIssues.push('SVG#' + idx + ' text overlap: "' + a.text + '" vs "' + b.text + '"');
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
                              return { scrollH: st.scrollHeight, clientH: st.clientHeight, maxBottom, svgIssues,
                                       longTexts, rawDollars: sc.innerText.includes('$$') };
                            }"""
                        )
                        location = f"EP {ep.ep_num} {sc.scene_id} beat {bi}, frame {index}"
                        if ov["rawDollars"]:
                            dollar_leaks.append(location)
                        if ov["scrollH"] > ov["clientH"] + 2 or ov["maxBottom"] > args.max_bottom:
                            overflows.append(f"{location}: {ov}")
                        for si_msg in ov.get("svgIssues", []):
                            overflows.append(f"{location}: {si_msg}")
                        for lt in ov.get("longTexts", []):
                            if lt not in seen_dense_texts:
                                seen_dense_texts.add(lt)
                                pedagogy_warns.append(
                                    f"EP {ep.ep_num} {sc.scene_id} beat {bi}: dense slide prose (>85 chars, risk of narration redundancy): {lt}"
                                )
                if args.sample_dir:
                    page.screenshot(
                        path=os.path.join(
                            args.sample_dir, f"ep_{ep.ep_num}_{sc.scene_id}.jpg"
                        ),
                        type="jpeg",
                        quality=88,
                    )
            for pw in pedagogy_warns:
                print(f"[PEDAGOGY WARN] {pw}")
            print(
                f"EP {ep.ep_num}: {len(ep.scenes)} scenes, {len(timeline)} beats, "
                f"{sum(len(group) for group in samples.values())} sampled frames at {args.fps} fps"
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

    print("Sampled frames passed JavaScript, KaTeX and DOM/SVG layout checks.")


if __name__ == "__main__":
    main()

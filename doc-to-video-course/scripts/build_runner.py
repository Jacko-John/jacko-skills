"""Parallel episode renderer + post-render ffmpeg verification helper."""
import argparse
import glob
import importlib.util
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from video_engine import DEFAULT_RATE, DEFAULT_VOICE, FFMPEG, Episode, render_episode


def _discover_episode_files(spec_dir: str, pattern: str = "ep*.py") -> list[str]:
    return sorted(glob.glob(os.path.join(spec_dir, pattern)))


def _load_one(path: str, spec_dir: str) -> Episode:
    if spec_dir not in sys.path:
        sys.path.insert(0, spec_dir)
    if SCRIPT_DIR not in sys.path:
        sys.path.insert(0, SCRIPT_DIR)
    mod_name = os.path.splitext(os.path.basename(path))[0]
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if hasattr(mod, "build_episode"):
        return mod.build_episode()
    for attr in dir(mod):
        if attr.startswith("build_ep") and callable(getattr(mod, attr)):
            return getattr(mod, attr)()
    raise ValueError(f"No build_episode() or build_ep*() found in {path}")


def _worker(args_tuple) -> dict:
    path, spec_dir, out_dir, voice, rate = args_tuple
    ep = _load_one(path, spec_dir)
    return render_episode(ep, out_dir=out_dir, voice=voice, rate=rate)


def fmt_mmss(sec: float) -> str:
    total = int(round(sec))
    return f"{total // 60:02d}:{total % 60:02d}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec-dir", required=True, help="Directory with ep*.py files")
    parser.add_argument("--out-dir", required=True, help="Output directory for .mp4 and .srt")
    parser.add_argument("--pattern", default="ep*.py")
    parser.add_argument("--eps", default=None, help="Optional comma-separated 1-based indices")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--voice", default=DEFAULT_VOICE)
    parser.add_argument("--rate", default=DEFAULT_RATE)
    parser.add_argument("--verify-frames-dir", default=None, help="Optional dir to dump 1 mid-frame JPG per MP4")
    args = parser.parse_args()

    files = _discover_episode_files(args.spec_dir, args.pattern)
    if not files:
        raise SystemExit(f"No files matched {args.pattern} in {args.spec_dir}")

    if args.eps:
        wanted = {int(x.strip()) for x in args.eps.split(",") if x.strip()}
        selected = [files[i - 1] for i in sorted(wanted)]
    else:
        selected = files

    t0 = time.time()
    results = []
    if len(selected) == 1 or args.workers <= 1:
        for f in selected:
            results.append(_worker((f, args.spec_dir, args.out_dir, args.voice, args.rate)))
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futs = [
                ex.submit(_worker, (f, args.spec_dir, args.out_dir, args.voice, args.rate))
                for f in selected
            ]
            for fut in as_completed(futs):
                results.append(fut.result())

    results.sort(key=lambda r: r["ep_num"])
    for r in results:
        r["duration_mmss"] = fmt_mmss(r["duration_sec"])
        if args.verify_frames_dir:
            os.makedirs(args.verify_frames_dir, exist_ok=True)
            ss = min(max(1.0, r["duration_sec"] * 0.45), max(1.0, r["duration_sec"] - 1.0))
            jpg_out = os.path.join(args.verify_frames_dir, f"ep_{r['ep_num']}_verify.jpg")
            subprocess.run(
                [FFMPEG, "-y", "-ss", f"{ss:.1f}", "-i", r["mp4"], "-vframes", "1", jpg_out],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            r["verify_frame"] = jpg_out

    manifest_path = os.path.join(args.out_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    total_sec = sum(r["duration_sec"] for r in results)
    print(
        f"Rendered {len(results)} episode(s) in {time.time() - t0:.1f}s "
        f"(total course runtime {fmt_mmss(total_sec)}). Manifest: {manifest_path}"
    )


if __name__ == "__main__":
    main()

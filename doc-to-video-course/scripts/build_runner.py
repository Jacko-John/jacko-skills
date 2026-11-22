"""Parallel episode renderer + post-render ffmpeg verification helper."""
import argparse
import glob
import importlib.util
import json
import os
import subprocess
import sys
import time
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from concurrent.futures import ProcessPoolExecutor

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from video_engine import DEFAULT_RATE, DEFAULT_VOICE, FFMPEG, FPS, Episode, publication_lock, publish_files, render_episode


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


def _worker(args_tuple):
    path, spec_dir, out_dir, voice, rate, fps, preset = args_tuple
    ep = _load_one(path, spec_dir)
    # Private output names keep jobs independent even when two specs claim the same final name.
    result = render_episode(replace(ep, filename="video.mp4"), out_dir=out_dir, voice=voice,
                            rate=rate, fps=fps, preset=preset)
    return result, ep.filename


def fmt_mmss(sec: float) -> str:
    total = int(round(sec))
    return f"{total // 60:02d}:{total % 60:02d}"


def _render_batch(selected, staging, args, fps, preset):
    jobs = [
        (path, args.spec_dir, str(staging / str(index)), args.voice, args.rate, fps, preset)
        for index, path in enumerate(selected)
    ]
    if len(jobs) == 1 or args.workers <= 1:
        return [_worker(job) for job in jobs]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        return list(pool.map(_worker, jobs))


def _publish_batch(results, out_dir, staging, partial, verify_dir, verify_staging):
    files = []
    new_rows = {}
    for index, (row, filename) in enumerate(results):
        number = row["ep_num"]
        if number in new_rows:
            raise ValueError(f"Duplicate episode number {number}")
        new_rows[number] = row
        row["duration_mmss"] = fmt_mmss(row["duration_sec"])
        video = out_dir / filename
        if verify_dir is not None:
            target = verify_dir / f"ep_{number}_verify.jpg"
            image = verify_staging / f"{index}.jpg"
            at = row["duration_sec"] * 0.45
            subprocess.run(
                [FFMPEG, "-y", "-loglevel", "error", "-ss", f"{at:.6f}", "-i", row["mp4"],
                 "-frames:v", "1", str(image)], check=True,
            )
            files.append((image, target))
            row["verify_frame"] = str(target)
        for key, target in (("mp4", video), ("srt", video.with_suffix(".srt"))):
            files.append((Path(row[key]), target))
            row[key] = str(target)

    manifest = out_dir / "manifest.json"
    # Read under the same lock as the final replacements, so simultaneous partial
    # renders merge with the newest manifest. Readers see complete JSON at all times.
    with publication_lock(out_dir):
        rows = {}
        if partial and manifest.exists():
            with manifest.open(encoding="utf-8") as f:
                rows = {old["ep_num"]: old for old in json.load(f)}
        rows.update(new_rows)
        merged = sorted(rows.values(), key=lambda row: row["ep_num"])
        media = [Path(row[field]).resolve() for row in merged for field in ("mp4", "srt")]
        if len(media) != len(set(media)):
            raise ValueError("Multiple episodes would publish to the same media path")
        staged_manifest = staging / "manifest.json"
        staged_manifest.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
        publish_files([*files, (staged_manifest, manifest)])
    return merged


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec-dir", required=True, help="Directory with ep*.py files")
    parser.add_argument("--out-dir", required=True, help="Output directory for .mp4 and .srt")
    parser.add_argument("--pattern", default="ep*.py")
    parser.add_argument("--eps", default=None, help="Optional comma-separated 1-based indices")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--voice", default=DEFAULT_VOICE)
    parser.add_argument("--rate", default=DEFAULT_RATE)
    parser.add_argument("--fps", type=int, default=FPS, help="Target video framerate (default 60)")
    parser.add_argument("--draft", action="store_true", help="Fast 24fps preview mode")
    parser.add_argument("--verify-frames-dir", default=None, help="Optional dir to dump 1 mid-frame JPG per MP4")
    args = parser.parse_args()

    fps = 24 if args.draft else args.fps
    preset = "veryfast" if args.draft else "fast"

    files = _discover_episode_files(args.spec_dir, args.pattern)
    if not files:
        raise SystemExit(f"No files matched {args.pattern} in {args.spec_dir}")

    if args.eps:
        wanted = {int(x.strip()) for x in args.eps.split(",") if x.strip()}
        if not wanted or min(wanted) < 1 or max(wanted) > len(files):
            parser.error(f"--eps must contain indices from 1 to {len(files)}")
        selected = [files[i - 1] for i in sorted(wanted)]
    else:
        selected = files

    t0 = time.time()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    verify_dir = Path(args.verify_frames_dir) if args.verify_frames_dir else None
    with ExitStack() as cleanup:
        staging = Path(cleanup.enter_context(TemporaryDirectory(prefix=".course-build-", dir=out_dir)))
        verify_staging = None
        if verify_dir is not None:
            verify_dir.mkdir(parents=True, exist_ok=True)
            verify_staging = Path(cleanup.enter_context(TemporaryDirectory(prefix=".course-verify-", dir=verify_dir)))
        results = _render_batch(selected, staging, args, fps, preset)
        course = _publish_batch(results, out_dir, staging, bool(args.eps), verify_dir, verify_staging)

    total_sec = sum(row["duration_sec"] for row in course)
    print(
        f"Rendered {len(results)} episode(s) in {time.time() - t0:.1f}s "
        f"(total course runtime {fmt_mmss(total_sec)}). Manifest: {out_dir / 'manifest.json'}"
    )


if __name__ == "__main__":
    main()

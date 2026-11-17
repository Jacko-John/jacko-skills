---
name: doc-to-video-course
description: >-
  Turn technical documents, interactive HTML explainers, papers, or homework guides
  into a beginner-friendly, multi-episode 1080p MP4 video course with Modern Keynote Studio
  visuals, synced neural Chinese/English voiceover, animated KaTeX math, shaded SVG diagrams,
  code spotlighting, SRT subtitles, and an HTML5 course player hub. Use when the user asks to
  create an explanatory video, narrated walkthrough video, or video course from a document.
---

# Document-to-Video Course Pipeline (Modern Keynote Studio)

Produces multi-episode `1920×1080 @ 30fps` `.mp4` lectures in an **Apple / Linear Keynote Studio** visual aesthetic: warm alabaster dot-grid canvas, large editorial typography, borderless spatial hierarchy, shaded SVG area charts with arrowhead leader callouts, macOS-style dark code spotlight windows, lightweight frosted cinema subtitles, `.srt` files, and a matching `video-course.html` playback hub.

## Workflow

### Step 1: Audit Document & Verify Environment
1. Read the source document completely and inventory:
   - Core sections, target audience pain points, and beginner "confusion traps" (e.g., notation mismatches, patch sizes, transpose conventions, hidden assumptions).
   - Exact numbers, formulas, tables, code blocks, and referenced local images (warn the user immediately if referenced relative images are missing).
2. Confirm runtime dependencies (`uv` provisions `playwright`, `edge-tts`, and `imageio-ffmpeg` on demand):
   - Verify Chromium/Chrome exists via `video_engine.find_chrome_exe()`.
   - Bootstrap offline KaTeX fonts/JS once:
     ```bash
     python3 <skill_dir>/scripts/setup_katex.py
     ```

### Step 2: Clarify Preferences Before Generating
Unless already specified, ask concise multiple-choice questions (`ask_question`) covering:
1. **Delivery structure**: multi-episode chaptered series + course hub (recommended) vs 1–2 pilot episodes first vs single merged video.
2. **Voice style**: `zh-CN-YunxiNeural` (calm male), `zh-CN-XiaoxiaoNeural` (clear female), dual-host Q&A, or silent animated captions.
3. **Pedagogical focus**: full zero-to-one beginner walkthrough (intuition + math derivations + experiments + code pitfalls) vs theory-focused vs implementation-focused.

### Step 3: Design Episodes & Keynote Visual Choreography
Split the source material into **3–6 episodes (2–5 minutes each)** and write one Python spec file per episode (`ep01.py`, `ep02.py`, ...) defining `build_episode() -> Episode` (see [sample_episode.py](./examples/sample_episode.py)).

Follow these Modern Keynote Studio layout principles (details in [design-and-pitfalls.md](./references/design-and-pitfalls.md)):
- **Vary slide composition across scenes**: Alternate between centered oversized equation spotlights (`.math-stage` + 3 borderless columns), open editorial splits (`.studio-split` with `.note-block` and `data-dim-past="1"`), dark `.code-window` terminals, and hairline borderless `table.data` views instead of wrapping everything in boxes.
- **Progressive disclosure**: Use `data-step="0"`, `data-step="1"`, ... so ideas enter smoothly as the narrator speaks each point.
- **High-craft SVG animations**: Use `svgAreaPolyline` for shaded curves, `svgDot(..., true)` for glowing tracking dots, and `svgCalloutArrow` / `url(#arr-...)` vector arrowheads to annotate peaks and vectors (`continuous=True` on beats sweeping parameters).
- **Quiz pauses**: Allocate a `continuous=True` thinking progress bar beat (`reveal: False`, `pause_after=1.2`) before revealing the answer (`reveal: True`).
- **Dual `(sub, tts)` text**: Keep `sub` short (`15–34` chars) with clean math notation (`ΔR`, `Rᶜ`, `ViT`, `IoU`); expand symbols/acronyms in `tts` (`Delta R`, `R c`, `V I T`, `I O U`, `lambda`) for natural speech.

### Step 4: Pre-Render Validation Gate (Mandatory)
Before rendering any video frames, run the Chromium validation check across all episode files to catch Python LaTeX escape warnings, JS exceptions, unrendered `$$`, and layout collisions with the bottom subtitle zone (`maxBottom > 968`):
```bash
uv run --with playwright --with edge-tts --with imageio-ffmpeg \
  python <skill_dir>/scripts/validate_episodes.py \
  --spec-dir <spec_dir> --sample-dir <sample_dir>
```
Inspect generated sample `.jpg` images with `read_file` if layout density is high.

### Step 5: Parallel Render & Output Verification
1. Render all episodes (or pilot subset `--eps 1,2`) in parallel using `build_runner.py`:
   ```bash
   uv run --with playwright --with edge-tts --with imageio-ffmpeg \
     python <skill_dir>/scripts/build_runner.py \
     --spec-dir <spec_dir> --out-dir <workspace>/videos \
     --workers 3 --voice zh-CN-YunxiNeural --rate="-3%" \
     --verify-frames-dir <verify_dir>
   ```
2. Visually inspect the extracted verification frames (`<verify_dir>/ep_*_verify.jpg`) via `read_file` and confirm `videos/manifest.json` reports expected durations and non-zero sizes.

### Step 6: Build Course Playback Hub
Generate `<workspace>/video-course.html` directly from `manifest.json` so durations and file links match actual outputs:
```bash
python3 <skill_dir>/scripts/generate_course_hub.py \
  --manifest <workspace>/videos/manifest.json \
  --out-html <workspace>/video-course.html \
  --title "<Course Title>" \
  --source-doc "<relative_source_doc>"
```
Verify `video-course.html` in headless Chromium (episode switching + zero JS errors) before reporting completion.

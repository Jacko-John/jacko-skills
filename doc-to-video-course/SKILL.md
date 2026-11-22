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

Produces multi-episode `1920×1080 @ 30fps` `.mp4` lectures in an **Apple / Linear Keynote Studio** visual aesthetic: warm alabaster dot-grid canvas, Assertion-Evidence editorial typography, borderless spatial hierarchy, animated vector diagrams and area charts, macOS-style dark code spotlight windows, lightweight frosted cinema subtitles, `.srt` files, and a `video-course.html` playback hub.

**Default Audience Assumption**: Unless the user explicitly requests an advanced/compact cut, **always design for a zero-to-one beginner**—no assumed paper context, concrete intuition before formal notation, explicit confusion-trap unpacking, and slow, multi-angle deep dives on core difficulties.

## Workflow

### Step 1: Audit Document & Triage Depth
1. Read the source document completely and inventory:
   - **Prerequisites & beginner confusion traps**: implicit notation, transpose/shape conventions, sign flips, or "why do we even need this?" gaps that will trip up a newcomer.
   - **Zoom-Lens importance triage**: Separate the material into:
     - *Wide-Angle Context / Transitions* (keep brisk: ~15% of beats).
     - *Core Mechanisms & Key Difficulties* (allocate **55–65% of beats**; unpack from multiple angles).
     - *Synthesis & Takeaways* (~20–25% of beats).
   - Exact numbers, formulas, tables, code blocks, and referenced local images (warn immediately if referenced relative images are missing).
2. Confirm runtime dependencies (`uv` provisions `playwright`, `edge-tts`, and `imageio-ffmpeg` on demand):
   - Verify Chromium/Chrome exists via `video_engine.find_chrome_exe()`.
   - Bootstrap offline KaTeX fonts/JS once:
     ```bash
     python3 <skill_dir>/scripts/setup_katex.py
     ```

### Step 2: Clarify Delivery & Voice (Keep Beginner Deep-Dive Default)
Unless already specified, ask concise multiple-choice questions (`ask_question`) covering:
1. **Delivery structure**: multi-episode chaptered series + course hub (recommended) vs 1–2 pilot episodes first vs single merged video.
2. **Voice style**: `zh-CN-YunxiNeural` (calm male), `zh-CN-XiaoxiaoNeural` (clear female), dual-host Q&A, or silent animated captions.

*(Do not downgrade beginner depth by default; only switch to a compact/expert cut if the user explicitly asks for it.)*

### Step 3: Narration-First Storyboard & Keynote Choreography
Split the source material into **3–6 episodes (2–5 minutes each)** and write one Python spec file per episode (`ep01.py`, `ep02.py`, ...) defining `build_episode() -> Episode` (see [sample_episode.py](./examples/sample_episode.py)).

Follow the full instructional standards in [pedagogy-and-choreography.md](./references/pedagogy-and-choreography.md) and visual/technical rules in [design-and-pitfalls.md](./references/design-and-pitfalls.md):

1. **Zoom-Lens Pacing & Multi-Angle Deep Dives**:
   - Move briskly through background and transitions; spend **55–65% of beats** on the core mechanism/difficulty.
   - Unpack every core concept from **at least 2–3 complementary angles** in sequence: (a) a concrete toy/numerical example (`Concrete`), (b) dynamic visual intuition (`Pictorial`), (c) formula/code term-by-term mapping (`Abstract`), and (d) boundary cases or common beginner mistakes.
   - Open with a concrete pain point or puzzle before introducing formal equations ("earn the abstraction").

2. **Narration-First Script & Zero-Redundancy Slides (Assertion-Evidence)**:
   - Write the atomic spoken `Beat`s first (`~2–4s` per beat, one micro-idea per beat), then design the **single visual delta** that enters or highlights during that Beat.
   - Use `.assertion-title` / `.k-title` for a **single-sentence takeaway claim**, not a generic topic noun.
   - Keep slide text to **short visual anchors** (`.term-chip`, `.kv` badges, 1-line labels, equations, code windows). Never put long prose paragraphs on screen that duplicate what TTS says, and never reveal unmentioned blocks on `data-step="0"`.

3. **Tight Audio–Animation Coupling & Anti-Transience**:
   - **Temporal Contiguity**: Trigger reveals (`data-step`), focus shifts (`data-focus-group` + `data-focus-step` / `cue={"focus": "..."}`), and SVG changes in the exact Beat whose narration refers to them.
   - **3-Beat Motion Pattern**: For `continuous=True` animations, establish the baseline first, animate smoothly across `ctx.p` **while keeping a dashed ghost reference** of the starting state, then hold on a consolidation beat (`pause_after=0.9..1.2`).
   - **Pause Budgeting**: Use `0.25–0.35s` inside a flowing trace, `0.8–1.2s` after key formulas/continuous sweeps, and `1.2–1.5s` for quiz thinking beats (`reveal: False`) before revealing the answer.
   - **Dual `(sub, tts)` text**: Keep `sub` short (`15–34` chars) with clean math notation (`ΔR`, `Rᶜ`, `ViT`, `IoU`); expand symbols/acronyms in `tts` (`Delta R`, `R c`, `V I T`, `I O U`, `lambda`) for natural speech.

### Step 4: Pre-Render Validation Gate (Mandatory)
Before rendering any video frames, run the Chromium validation check across all episode files to catch Python LaTeX escape warnings, JS exceptions, unrendered `$$`, layout/SVG collisions across **every beat** (including `continuous=True` endpoints), and `[PEDAGOGY WARN]` notices for static slides or dense prose:
```bash
uv run --with playwright --with edge-tts --with imageio-ffmpeg \
  python <skill_dir>/scripts/validate_episodes.py \
  --spec-dir <spec_dir> --sample-dir <sample_dir>
```
Inspect generated sample `.jpg` images with `read_file` to verify visual spacing and clarity.

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

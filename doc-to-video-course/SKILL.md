---
name: doc-to-video-course
description: >-
  Turn technical documents, interactive HTML explainers, papers, or homework guides
  into a beginner-friendly, multi-episode 1080p MP4 video course with warm alabaster
  centered motion-graphics animations, synced neural Chinese/English voiceover,
  in-situ KaTeX math, code spotlighting, SRT subtitles, and an HTML5 course player hub.
  Use when the user asks to create an explanatory video, narrated walkthrough video,
  or video course from a document.
---

# Document-to-Video Course Pipeline (Warm Alabaster Centered Studio)

Produces multi-episode `1920×1080 @ 60fps` `.mp4` lectures on a **warm alabaster minimalist canvas** (`#faf9f6` dot-grid) featuring **centered, distraction-free Motion Graphics** (inspired by *小白debug*'s concrete-metaphor & 3-step escalation storytelling), Chromium WebCodecs rendering with an FFmpeg H.264 delivery encode on the preferred VP9 path, synced neural voiceover, in-situ math, centered code spotlights, `.srt` subtitles, and a `video-course.html` playback hub.

**Default Audience & Visual Rule**: Unless the user explicitly requests otherwise, **always design for a zero-to-one beginner** AND keep **every core explanation centered on an uncluttered full-screen stage (`clean_stage=True`, `<canvas class="mg-stage">`)**—no cramped left-text / right-card PPT splits or unrelated sidebars competing with the animation.

## Workflow

### Step 1: Audit Document & Triage Depth
1. Read the source document completely and inventory:
   - **Prerequisites, concrete metaphors & confusion traps**: Turn abstract concepts into tangible mechanisms/analogies (packets, tollgates, queues, bars, coordinate flows) and list silent traps (transpose/shape mismatches, sign flips, boundary cases) that trip up newcomers.
   - **Zoom-Lens importance triage**:
     - *Wide-Angle Hook / Transitions* (~15% of beats): brisk pain point or puzzle opener.
     - *Core Mechanisms & Key Difficulties* (**55–65% of beats**): slow down and unpack from **2–3+ angles** using the 3-step escalation arc (naive working case $\rightarrow$ concrete failure/bottleneck $\rightarrow$ real mechanism + formula/code).
     - *Synthesis & Takeaways* (~20–25% of beats).
   - Exact numbers, formulas, tables, code blocks, and referenced local images (warn immediately if referenced relative images are missing).
2. Confirm runtime dependencies (`uv` provisions `playwright`, `edge-tts`, and `imageio-ffmpeg` on demand):
   - Validation and export share the same Chromium launcher. Install the Playwright browser on a new machine with `uv run --with playwright playwright install chromium`. On Linux, the installer also accepts `--with-deps` for required OS libraries. Playwright uses its own browser location, including a configured `PLAYWRIGHT_BROWSERS_PATH`. System Chromium or Chrome can serve as a fallback. To use a specific build, set `D2V_CHROME_EXE` to its executable path. [Playwright browser installation](https://playwright.dev/python/docs/browsers)
   - Bootstrap offline KaTeX fonts/JS once:
     ```bash
     uv run python <skill_dir>/scripts/setup_katex.py
     ```

### Step 2: Clarify Delivery & Voice (Keep Beginner Deep-Dive Default)
Unless already specified, ask about the following delivery choices:
1. **Delivery structure**: multi-episode chaptered series + course hub (recommended) vs 1–2 pilot episodes first vs single merged video.
2. **Voice style**: `zh-CN-YunxiNeural` (calm male), `zh-CN-XiaoxiaoNeural` (clear female), dual-host Q&A, or silent animated captions.

*(Do not downgrade beginner depth by default; only switch to a compact/expert cut if the user explicitly asks for it.)*

### Step 3: Narration-First Storyboard & Centered Motion Choreography
Split the source material into **3–6 episodes (2–5 minutes each)** and write one Python spec file per episode (`ep01.py`, `ep02.py`, ...) defining `build_episode() -> Episode` (see [sample_episode.py](./examples/sample_episode.py)).

Follow the full instructional standards in [pedagogy-and-choreography.md](./references/pedagogy-and-choreography.md) and visual/technical rules in [design-and-pitfalls.md](./references/design-and-pitfalls.md):

1. **Centered, Distraction-Free Stage (`clean_stage=True` + `<canvas class="mg-stage">`)**:
   - Use `<canvas class="mg-stage" width="1920" height="1080"></canvas>` with `clean_stage=True` on core explanation scenes so topbar chrome fades out and the animation owns the center of the warm alabaster `#faf9f6` canvas (`y = 90..880`).
   - Do **not** squash animations into a half-screen `.studio-split` sidebar card. Put supporting equations or code in centered overlays (`.float-math`, `.code-spotlight`) only on the beats where they are actively explained, and hide them (`data-hide-after`) when returning to full-canvas motion.

2. **小白debug-Style Concrete Storytelling & Fluid MG Motion**:
   - **3-Step Escalation**: Start with a concrete toy/metaphor (`mgNode`, `mgBar`, `mgPacket`), trigger a clear visual problem (`wiggle`, red bottleneck), then animate the real fix morphing smoothly into the general curve/architecture and in-situ formula (`mgFormula`).
   - Write a short spoken unit for each change the audience should follow. Mark the words that introduce the action and the words that establish its outcome. For example, `marks={"append": "追加", "query": "查询"}` and `easeInOut(ctx.motion(2, "append", "query"))` carry a token into the cache while that operation is being explained. Each mark refers to that beat's `tts` text. A completed move holds through later beats in the same scene.
   - Use a short entrance for identification, a longer travel or transformation for the mechanism, then a still frame to inspect the result. Leave a faint outline or reference curve while it helps the comparison. Choose the pause after listening to the actual narration.
   - **Dual `(sub, tts)` text**: Keep `sub` short (`15–34` chars) with clean math notation (`ΔR`, `Rᶜ`, `ViT`, `IoU`); write conversational Mandarin in `tts` and expand symbols/acronyms (`Delta R`, `R c`, `V I T`, `I O U`, `lambda`) for natural speech.

### Step 4: Pre-Render Validation Gate (Mandatory)
Run the validator with the same voice and rate as the render. Inspect its samples for label collisions, safe margins, and the placement of the active subject. The browser can measure DOM and SVG labels. Canvas text and moving elements need visual inspection.
```bash
uv run --with playwright --with edge-tts --with imageio-ffmpeg \
  python <skill_dir>/scripts/validate_episodes.py \
  --spec-dir <spec_dir> --sample-dir <sample_dir>
```
Check the last frame before a change of beat and the first frame after it. A retained object should still be in the same place. Check each trigger against the narration, including the instant its target reaches its destination. For the bundled example, pass `--pattern sample_episode.py` to the validator and renderer.

### Step 5: Parallel Render & Output Verification
1. Export a 24fps draft with `--draft` to listen to the sequence while iterating. Export the final MP4 at the default 60fps with the flag omitted. The preferred full-quality path encodes VP9 at quantizer 12 in Chromium, then H.264 at CRF 16 in FFmpeg.
   ```bash
   uv run --with playwright --with edge-tts --with imageio-ffmpeg \
     python <skill_dir>/scripts/build_runner.py \
     --spec-dir <spec_dir> --out-dir <workspace>/videos \
     --workers 3 --voice zh-CN-YunxiNeural --rate="-3%" \
     --verify-frames-dir <verify_dir>
   ```
2. Review the final MP4 at normal speed with sound. Scrub through the actual transition frames where pace or continuity is doubtful. Look closely at moving fine strokes, text edges, and the dots behind each entrance for block artifacts. Verify the encoded dimensions, frame cadence, and audio/video durations. The SRT gives sentence times and the recorded word boundaries locate the triggers. A midpoint JPEG can confirm the layout of that frame.
3. To revise one episode in an existing course, use the same output directory and select it with `--eps` (1-based indices in the sorted spec file list). The runner merges the selected episode numbers into the course manifest. A full run rebuilds the manifest from the selected spec directory. Rendering and requested verification stills complete in staging before the batch replaces the published files.

### Step 6: Build Course Playback Hub
Generate `<workspace>/video-course.html` directly from `manifest.json` so durations and file links match actual outputs:
```bash
uv run python <skill_dir>/scripts/generate_course_hub.py \
  --manifest <workspace>/videos/manifest.json \
  --out-html <workspace>/video-course.html \
  --title "<Course Title>" \
  --source-doc "<relative_source_doc>"
```
Verify `video-course.html` in headless Chromium (episode switching + zero JS errors) before reporting completion.

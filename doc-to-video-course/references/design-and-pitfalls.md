# Design Guidelines & Verified Technical Pitfalls

See [pedagogy-and-choreography.md](./pedagogy-and-choreography.md) for instructional sequencing, *小白debug*-style concrete storytelling, and centered animation choreography.

## 1. Visual Design System (Warm Alabaster Centered Studio)
- **Atmosphere**: Warm alabaster (`#faf9f6`) with subtle radial ambient lighting and `28px` micro dot-grid. **Keep this light, warm, high-contrast canvas** as the unified visual identity.
- **Primary Layout — Full-Stage Centered Canvas (`clean_stage=True` + `<canvas class="mg-stage">`)**:
  - For all core mechanism explanations, use a transparent full-bleed `<canvas class="mg-stage" width="1920" height="1080"></canvas>` layered directly over `.frame-shell` (so `mgClear(ctx)` reveals the warm alabaster dot-grid underneath automatically!).
  - Set `clean_stage=True` on `Scene` to hide topbar chrome during deep dives so the centered animation has **zero peripheral distraction**.
  - Let objects enter with `spring()`, travel along pipes with `mgPacket()`, shake on errors with `wiggle()`, and zoom cleanly with `mgCamera()` instead of boxing graphics inside `.svg-card` rectangles or permanent `.studio-split` sidebars.
- **Supporting Centered Overlays** (use sparingly, fade out via `data-hide-after` when canvas motion takes center stage):
  - `.center-stage` + `.k-hero-title`: Clean opening hook or closing takeaway centered on the open canvas.
  - `.float-math`: Borderless floating KaTeX pill positioned cleanly without blocking the visual.
  - `.code-spotlight`: Centered macOS `#0b1120` `.code-window` (`width: min(980px, 90%)`) with `.code-line.hi` / `.code-line.warn` line highlighting for dedicated code walkthrough beats.
  - Legacy `.studio-split` / `.svg-card` / `table.data` remain supported for backward compatibility or brief end-of-episode comparison tables, **not** as the default for core concept explanations.
- **Lightweight Subtitle Strip**: `rgba(255, 255, 255, 0.86)` frosted capsule at `bottom: 24px` (`25.5px` crisp `#0f172a` ink) — high contrast without looking like a heavy black block.

## 2. Warm Alabaster Motion Graphics (`MG`) Canvas Toolkit (`SHARED_JS`)
Available directly inside `js_frame` when driving `<canvas class="mg-stage">`:
- `ctx.motion(beatIndex, start, end)` returns progress along the scene clock. The zero-based beat index belongs to this scene. A string names a `Beat.marks` entry in that beat. A number is a time in seconds from its start, and `null` as the end uses the end of its speech. Progress rises linearly from 0 at the start to 1 at the end and holds there. An explicit end time past the next sentence boundary carries the motion into that sentence. Set `continuous=True` on each beat with changing visuals.
- **Fast/Slow Rhythm Contrast (Avoid "uniform cruise speed")**:
  - Do **not** stretch every single card pop across a whole spoken clause via `ctx.motion(b, mark1, mark2)`. Use **`ctx.snap(beatIndex, mark, durSec = 0.26)`** for crisp staccato pops/highlights/badge stamps (`0.18s–0.30s`), **`easeOutQuart(ctx.snap(...))`** for fast vector arrow shoots, **`wiggle(ctx.elapsed(beatIndex, mark), freq, amp)`** for failure shakes, and reserve **`easeWhip(ctx.motion(...))`** (`0.65s–1.10s`) for camera glides, card transfers, and curve sweeps. Fast pops + calm breathing holds create a lively Keynote/小白debug rhythm.
- Mark the action's beginning and its destination in the narration. For “追加进抽屉，再用新的查询读回来”, define `marks={"append": "追加", "read": "查询"}`. Then `easeWhip(ctx.motion(2, "append", "read"))` gives the packet time to travel while the first clause is spoken. Check both ends against the selected voice. If two marks resolve to the same word boundary, choose distinct spoken phrases.
- `mgPop(progress)` uses `spring(t)` overshoot for crisp elastic card entrances (`scale` settles past 1.0 briefly without sluggish linear creep). Compose the picture for the requested frame with `mgClear(c)` and `mgCamera(c, scale, panX, panY)` inside a saved Canvas context. The resting geometry at the end of a movement is the starting geometry for the next one.
- **Entities & Flow (*小白debug* MG primitives)**:
  - `mgNode(c, x, y, w, h, title, sub, { state, shakeX, shakeY, alpha })`: Crisp flat-modern box (`state`: `'idle' | 'active' | 'warm' | 'green' | 'amber' | 'dim'`).
  - `mgArrow(c, x1, y1, x2, y2, { progress, curve, color, dash, label })`: Progressive straight/curved vector arrow with optional centered pill label.
  - `mgPacket(c, pts, progress, label, { color, r })`: Animated glowing packet/token moving smoothly along a multi-point path `pts`.
  - `mgPill(c, cx, cy, text, { bg, stroke, fg, alpha })`: Crisp rounded callout badge.
- **Math & Curves & Studio Containers**:
  - `mgAxes(c, bounds, { xTicks, yTicks, xLabel, alpha })`: Open hairline axes returning `{ sx, sy, baseY }`.
  - `mgCurve(c, sx, sy, fn, x0, x1, { progress, color, dash, fill, baseY, lw })`: Smooth function curve with progressive drawing and optional soft area fill.
  - `mgDot(c, x, y, color, r, halo)` and `mgFormula(c, cx, cy, text, { alpha })`.
  - `mgHeader(c, cx, cy, eyebrow, title, { alpha })`: Crisp Assertion-Evidence eyebrow + headline without hand-tuned font boilerplate.
  - `mgPanel(c, x, y, w, h, title, { state })`: Soft-tinted container card (`'idle' | 'active' | 'warm' | 'green' | 'amber'`) for drawers/groups; populate inner entries as `mgNode` sub-cards rather than bare unboxed text rows.
  - `mgCodeWindow(c, x, y, w, h, { filename, lines, commentOffset })`: macOS traffic-light dark `#0b1120` window with Python token coloring, per-line spotlight glow (`highlight: 0..1`), and aligned right-hand `# comment` annotations—preserving fast pure-Canvas compositing without degrading code scenes to bare black boxes.

### Visual Craft & Anti-Bloat Rules
- **Vibrant semantic palette & information hierarchy**: Use the palette's high-contrast functional tones (`#2563eb` active, `#059669` cached/kept, `#d9483b` waste/discarded, `#d97706` threshold/query) with real two-line `mgNode` cards and `mgPill` callout badges rather than desaturated grey text or single-line labels.
- **Keep causal context on screen side-by-side**: When transitioning from mechanism → graph/matrix (e.g., naive loop → `O(N²)` chart, single-step flow → attention triangle), glide/scale the primary diagram aside with `mgCamera` or coordinated offsets so cause and effect stay visible together—do not fade out the whole stage to an isolated miniature diagram.
- **Never cross-fade two titles at the same `(x, y)`**: Overlapping `alpha` and `1 - alpha` labels in-place produce unreadable muddled glyphs mid-transition. Use discrete non-overlapping sub-positions, a single persistent panel title, or an explicit vertical swap (`yOff`) with a dead zone.

## 3. Safe-Area Layout Rules (`1920 × 1080`)
- **Subtitle safe zone**: Keep primary centered visuals and annotations within `y = 90..880` so nothing collides with the bottom frosted subtitle strip (`bottom: 24px`, top around `y ≈ 980px`). `validate_episodes.py` enforces `maxBottom <= 968` on visible DOM cards/SVGs/code windows across **all beats**.
- A DOM `data-step` begins at opacity 0. The default entrance takes 0.7 s (`DOM_ENTER_SEC`) and uses `easeInOut` to accelerate and settle. Let the running frame control opacity through this interval. For words spoken later in the sentence, use the measured word interval in the scene's own animation.
- For a one-time change such as sliding a drawer across the stage, use `const x = lerp(720, 980, easeInOut(ctx.motion(1, 0, "arrive")))`. On the next beat the same expression still yields 980. A calculation using only the current `ctx.beatTime` starts over at every sentence boundary.
- **Never mix `svgFrame()` with prior elements in the same `<svg>`**: If using legacy SVG charts, `svgFrame()` resets `svg.innerHTML = ""`. Split stacked diagrams into separate `<svg>` elements.

## 4. Code Blocks & LaTeX Escaping
- **Newline doubling inside `<pre>`**: Wrap lines in `<span class="code-line">...</span>` with NO literal `\n` between spans (`pre.code { white-space: normal; }` and `.code-line { display: block; white-space: pre; }`).
- **Python LaTeX strings**: Always double-escape backslashes (`\\mathrm`, `\\frac`, `\\top`) or use raw strings `r"""..."""` so Python 3.12+ does not emit `SyntaxWarning`.
- **Offline KaTeX**: Local KaTeX `0.16.11` assets (`setup_katex.py`) prevent CDN timeouts across Chromium renders.

## 5. Media Pipeline Gotchas & Speed Controls
- **Playwright's `ffmpeg-mac` is WebM-only**: Always use **`imageio-ffmpeg`** (`imageio_ffmpeg.get_ffmpeg_exe()`) for `libx264` + `aac` `.mp4` encoding.
- The renderer calls `window.seekToState(payload)` for a requested frame. Derive the full visual state from this payload. Repeated seeks and out-of-order frame checks should draw the same picture.
- `build_runner.py --draft` writes a 24fps MP4. Full exports default to 1920 × 1080 at 60fps. Chromium prefers WebCodecs VP9 with quantizer 12 at 60fps (16 at 24fps), followed by FFmpeg `libx264` encoding. The default full-quality VP9 path uses CRF 16. Browser support can select AVC or a screenshot-based path. Inspect the exported frames for block artifacts on the path actually used.
- Preflight and both encoders use Chromium's page layout, installed fonts, and subtitle wrapping. A clean, full-size Canvas can reuse the native page background and caption between frames. Hidden siblings keep this optimization. Visible overlays and CSS-controlled entrances use native page capture. When an object crosses behind the standard subtitle, the compositor refreshes that region to retain the browser's blur and stacking order.
- To measure a new rendering environment, run the [offline compositing benchmark](../tests/benchmark_compositing.py) using the command in its module header. It alternates two visually identical scenes and reports wall-clock time, native screenshot counts, and decoded frame matches. Compare timings on the same machine with the same Chromium executable.
- **Sample-exact A/V sync**: Synthesize each `Beat` individually with `edge-tts`, decode MP3 → `48000 Hz` stereo `s16` PCM WAV, and concatenate with exact sample-counted silence (`pause_after * 48000` frames).

## 6. TTS Pronunciation & Subtitle Hygiene
Write each `Beat(sub=..., tts=...)` separately:
- **`sub`** (displayed & `.srt`): Keep concise (`15–34` Chinese chars) with crisp mathematical notation (`ΔR`, `Rᶜ`, `ViT`, `IoU`, `ReLU`, `λ = 5`, `slogdet`).
- **`tts`** (spoken by `edge-tts`): Expand tricky symbols/acronyms so Chinese neural TTS (`zh-CN-YunxiNeural` / `zh-CN-XiaoxiaoNeural`) pronounces them naturally (`V I T`, `M A E`, `I O U`, `M S S A`, `R c`, `Delta R`, `L 1`, `lambda`, `theta`, `tau`, `D 转置 y`).

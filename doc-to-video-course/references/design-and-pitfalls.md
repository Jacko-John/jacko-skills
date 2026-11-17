# Design Guidelines & Verified Technical Pitfalls

## 1. Visual Design System (Modern Keynote Studio)
- **Atmosphere**: Warm alabaster (`#faf9f6`) with subtle radial ambient lighting and `28px` micro dot-grid; avoid heavy gray borders around every text block.
- **Spatial Variety**: Mix layouts across consecutive scenes instead of repeating the same 2-column card box:
  - Centered Hero / Equation Spotlight (oversized `.math-stage` + 3 borderless columns below)
  - `.studio-split` (`.studio-left` open `.note-block` accents with `data-dim-past="1"` + `.studio-right` elevated `.svg-card` / `.glass-panel`)
  - `.code-window` (macOS-style `#0b1120` dark window chrome + `.code-line.hi` spotlight bar)
  - Borderless Linear-style `table.data` (hairline horizontal dividers only)
- **Charts & Vector Graphics**:
  - `svgFrame()` draws horizontal hairline guides and baseline only (no closed outer box).
  - Use `svgAreaPolyline(svg, pts, color, gradId, baseY)` for shaded area curves (`grad-blue`, `grad-red`, `grad-green`, `grad-amber`).
  - Use `svgDot(svg, x, y, color, r, true)` for glowing halo markers and `svgCalloutArrow(...)` for curved leader-line annotations pointing directly to curve peaks/kinks.
- **Lightweight Subtitle Strip**: `rgba(255, 255, 255, 0.86)` frosted capsule at `bottom: 24px` (`25.5px` crisp `#0f172a` ink) — high contrast without looking like a heavy black block.

## 2. Safe-Area Layout Rules (`1920 × 1080`)
- **Top header bar**: `68px` tall (`y = 0..68`).
- **Content stage**: `padding: 26px 68px 104px`, meaning all visible elements **must end at `y <= 974px`** (`validate_episodes.py` enforces `maxBottom <= 968` by default for extra breathing room above the subtitle strip).
- **Progressive reveal (no ghosting future steps!)**: Never draw unrevealed future sections at `opacity: 0.35` or `0.40`. Keep unrevealed content completely hidden (`opacity: 0`) until its step arrives, then fade/slide it in smoothly over `~0.45s` (which falls inside `anim_settle_sec = 0.75s` so `video_engine.py` captures smooth 30fps entrance frames automatically).
- **Never mix `svgFrame()` with prior elements in the same `<svg>`**: `svgFrame()` resets `svg.innerHTML = ""` and wipes out any preceding shapes/labels. Always split stacked diagrams or charts into separate `<svg>` containers (e.g., `#top-svg` and `#bot-svg`).
- **Avoid tall multi-row SVG stacks**: When stacking 2 SVGs vertically in a `.svg-card`, cap their combined `viewBox` heights around `540–580px` total so readout pills sit cleanly above `968px`.

## 3. Code Blocks & LaTeX Escaping
- **Newline doubling inside `<pre>`**: Wrap lines in `<span class="code-line">...</span>` with NO literal `\n` between spans (`pre.code { white-space: normal; }` and `.code-line { display: block; white-space: pre; }`).
- **Python LaTeX strings**: Always double-escape backslashes (`\\mathrm`, `\\frac`, `\\top`) or use raw strings `r"""..."""` so Python 3.12+ does not emit `SyntaxWarning`.
- **Offline KaTeX**: Local KaTeX `0.16.11` assets (`setup_katex.py`) prevent CDN timeouts across Chromium renders.

## 4. Media Pipeline Gotchas (macOS / Linux)
- **Playwright's `ffmpeg-mac` is WebM-only**: Always use **`imageio-ffmpeg`** (`imageio_ffmpeg.get_ffmpeg_exe()`) for `libx264` + `aac` `.mp4` encoding.
- **Deterministic frame rendering vs CSS transitions**: Never rely on CSS `transition:` for frame animations. Use `window.seekToState(payload)` driven by `stepTime` and `p` (`0..1` over the beat's speech duration).
- **Playwright `evaluate` signature**: Call `page.evaluate("(p) => window.seekToState(p)", payload)` rather than passing a bare function-name string.
- **Python 3.9 compatibility**: Keep helper scripts (`setup_katex.py`, `video_engine.py`) compatible with macOS `/usr/bin/python3` (`Optional[str]` instead of `str | None`).
- **Sample-exact A/V sync**: Synthesize each `Beat` individually with `edge-tts`, decode MP3 -> `48000 Hz` stereo `s16` PCM WAV, and concatenate with exact sample-counted silence (`pause_after * 48000` frames).

## 5. TTS Pronunciation & Subtitle Hygiene
Write each `Beat(sub=..., tts=...)` separately:
- **`sub`** (displayed & `.srt`): Keep concise (`15–34` Chinese chars) with crisp mathematical notation (`ΔR`, `Rᶜ`, `ViT`, `IoU`, `ReLU`, `λ = 5`, `slogdet`).
- **`tts`** (spoken by `edge-tts`): Expand tricky symbols/acronyms so Chinese neural TTS (`zh-CN-YunxiNeural` / `zh-CN-XiaoxiaoNeural`) pronounces them naturally (`V I T`, `M A E`, `I O U`, `M S S A`, `R c`, `Delta R`, `L 1`, `lambda`, `theta`, `tau`, `D 转置 y`).

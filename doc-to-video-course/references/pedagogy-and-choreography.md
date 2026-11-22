# Pedagogy & Animation-Narration Choreography Guide

This guide defines the instructional design standards for `doc-to-video-course`. The goal is not to summarize a document on slides, but to help a **zero-to-one beginner** build an accurate, durable mental model through synchronized visual storytelling.

---

## 1. Default Audience: Zero-to-One Beginner Deep-Dive

Unless the user explicitly requests a compact, expert, or code-only cut, **always treat the viewer as an intelligent beginner with no prior context from the source document**:

- **Context Self-Sufficiency**: Never assume the viewer remembers terminology, notation, or motivation from earlier sections or external papers. Restate what a symbol represents in plain language when it enters a new scene.
- **Earn Every Abstraction (Concrete → Pictorial → Abstract)**:
  1. **Concrete Hook / Pain Point**: Start with a small numerical example, everyday analogy, or concrete failure case ("what breaks if we do the naive thing?") before showing general notation.
  2. **Pictorial / Geometric Intuition**: Visualize how quantities move, transform, filter, or compete in space/time.
  3. **Formal Symbol / Code**: Introduce the equation or code only after the viewer already feels *why* it has that shape, and explicitly map each symbol back to the concrete example.
- **Unpack Beginner Confusion Traps**: Actively surface silent assumptions that trip up newcomers (e.g., matrix transpose conventions, off-by-one shapes, sign flips, units, boundary behavior when a hyperparameter hits `0` or `∞`).

---

## 2. Pacing & Emphasis: The Zoom-Lens Budget

Flat, uniform section-by-section coverage turns a lecture into a checklist. Use a **Zoom-Lens** rhythm so time goes where understanding is hardest:

| Phase | Target Beat Share | Pacing & Goal |
| :--- | :--- | :--- |
| **1. Wide-Angle Orientation (Zoom Out)** | ~15% | Fast, crisp framing: what problem are we solving, why care, and where does this piece sit in the whole system? Skip background trivia. |
| **2. Core Mechanism Deep-Dive (Zoom In)** | ~55–65% | Slow down. Unpack the 1–3 hardest or most central ideas from **multiple orthogonal angles** (see below). |
| **3. Synthesis & Bridge (Zoom Out)** | ~20–25% | Lock in the takeaway, contrast with alternatives/misconceptions, and link explicitly to the next scene or episode. |

### Mandatory Multi-Angle Rule for Core Concepts
Every core concept or difficult formula **must** be explained from at least **2–3 complementary angles** instead of a single pass:
1. **Numerical / Toy Trace**: Walk through 2–3 concrete numbers (e.g., `y = [0.2, 0.8, 1.5]` with `λ = 0.5`) so the mechanism is tangible.
2. **Visual / Dynamic Transformation**: Animate the curve, vector, flow, or matrix state changing continuously so the viewer *sees* the cause-and-effect relationship.
3. **Symbol / Code Mapping**: Highlight one term or code line at a time and tie it directly to what just moved on screen.
4. **Boundary / Counterexample Check**: Test an extreme case (`λ = 0`, `λ` too large) or expose a common wrong intuition ("many beginners think ReLU only clips negative inputs, but here...").

---

## 3. Narration-First Script & Assertion-Evidence Slides

### Workflow Order: Script Beats First, Visuals Second
Never design a dense slide first and write voiceover around it.
1. Break each scene into **atomic Beats** (`~2–4s` of speech each, covering **one** micro-claim or visual transition).
2. For each Beat, decide the **single visual delta** on screen: what appears, moves, dims, or lights up *while that sentence is spoken*.

### Assertion-Evidence Slide Hygiene (Zero Redundancy)
Guided by Mayer's **Redundancy Principle** and Michael Alley's **Assertion-Evidence** structure:
- **Takeaway Headline (`.assertion-title` / `.k-title`)**: State the scene's core conclusion as a concise, complete claim (e.g., `"λ 越大，阈值右移，更多小信号被直接置零"`), **not** a vague noun label (`"软阈值公式"`).
- **Visual Evidence + Short Anchors Only**: The stage holds diagrams, equations, code windows, numeric pills (`.term-chip` / `.kv`), and short structural labels (`<= 14` chars per label).
- **Ban Prose Paragraphs & Redundant Bullets**: Never put full sentences on screen that paraphrase or duplicate the voiceover. Long explanations belong in `tts` / `sub`; the slide holds only the visual anchors the eye needs while the ear listens.
- **No Premature Reveals**: Never give multiple sequential ideas the same `data-step="0"`. If a `.note-block` or code block is explained in Beat 2, it must stay hidden (`opacity: 0`) until Beat 2 arrives.

---

## 4. Coupling Animation & Narration (Fighting Transience)

Educational animations fail when motion outpaces working memory (**Transient Information Effect**). Follow these rules:

### A. Temporal Contiguity (Say It While It Moves)
- Trigger visual entrance, highlight, or SVG motion in the exact Beat whose narration describes it.
- Do not pack two separate visual steps into one static Beat. Split them into two short Beats so `seekToState` advances cleanly between them.

### B. Visual Signaling & Focus Dimming
- When a slide displays several items (e.g., 3 numerical examples, 4 pipeline stages, or 3 equation terms), use `data-focus-group` + `data-focus-step` (or `data-focus-id` + `cue={"focus": "..."}`) so the active item pops (`opacity: 1`, `.focus-active`) while sibling items automatically dim (`opacity: 0.34`).
- In SVG diagrams, pair motion with explicit visual cues: `svgDot(..., true)` for tracking halos, `svgCalloutArrow(...)` for kinks/peaks, and `svgBadgePill(...)` for live numerical readouts.

### C. The 3-Beat Anti-Transience Pattern for Dynamic Changes
Whenever animating a transformation (`continuous=True`), structure it as three beats so the viewer never loses track of what changed:
1. **Anchor Baseline Beat** (`continuous=False`): Show and name the starting state (`λ = 0` identity line / original distribution) first.
2. **Guided Motion + Ghost Reference Beat** (`continuous=True`): Animate the change across `ctx.p`, **while keeping a dashed ghost curve/outline of the baseline** on screen so the viewer directly compares *before* vs *after*.
3. **Consolidation Pause Beat** (`pause_after=0.9..1.2`): Stop motion at the target state, call out the key takeaway or readout pill, and give working memory a breath before advancing.

### D. Deliberate `pause_after` Budgeting
| Beat Transition Type | Recommended `pause_after` |
| :--- | :--- |
| Flowing steps within the same concrete example | `0.25s – 0.35s` |
| End of a derivation, key equation reveal, or major mental-model shift | `0.80s – 1.15s` |
| End of a `continuous=True` sweep or before a dense visual switch | `0.90s – 1.20s` |
| Quiz / "predict what happens" thinking beat (`reveal: False`) | `1.20s – 1.50s` |
| End of scene (enforced floor in `video_engine.py`: `>= 0.55s`) | `0.70s – 1.00s` |

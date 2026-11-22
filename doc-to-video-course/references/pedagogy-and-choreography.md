# Pedagogy & Animation-Narration Choreography Guide

This guide defines the instructional and motion-design standards for `doc-to-video-course`. The goal is not to put textbook pages on slides, but to help a **zero-to-one beginner** build an intuitive, durable mental model through **centered, distraction-free, living vector explanations** (combining Concrete-Pictorial-Abstract pedagogy with the relatable, step-by-step storytelling style of *小白debug* on a warm alabaster minimalist stage).

---

## 1. Default Audience: Zero-to-One Beginner Deep-Dive

Unless the user explicitly requests a compact or expert cut, **always treat the viewer as an intelligent beginner with no prior context from the source document**:

- **Context Self-Sufficiency**: Never assume the viewer remembers terminology, notation, or motivation from earlier sections or external papers. Explain what a symbol represents in plain language right when it appears.
- **Concrete Metaphor & Personification Hook (小白debug 具象拆解)**:
  - Never open a topic with an abstract textbook definition or a finished multi-box architecture diagram.
  - Open with a **relatable pain point, engineering puzzle, or concrete metaphor** (e.g., packets riding a conveyor belt, signals passing a tollgate/filter, a single machine crashing under load) whose mechanics map *faithfully* to the real mechanism.
- **3-Step Escalation Arc (拆碎 → 踩坑 → 破局)**:
  1. **Naive / Simple Version**: Show the simplest concrete case working (2–3 small numbers or 2 nodes).
  2. **Inject the Trap / Failure**: Trigger a concrete failure (`wiggle` shake, red bottleneck, or wrong naive guess) so the viewer *feels why* a naive solution breaks.
  3. **Mechanism & Abstraction**: Introduce the real fix in motion, and only **then** let the formal equation or code emerge in-situ, mapping each term back to what just moved on screen.
- **Unpack Beginner Confusion Traps**: Explicitly demonstrate boundary cases (`λ = 0`, off-by-one shapes, transpose mismatches, sign flips) visually rather than burying them in footnotes.

---

## 2. Pacing & Emphasis: The Zoom-Lens Budget

Flat, uniform section-by-section coverage turns a lecture into a checklist. Use a **Zoom-Lens** rhythm so time goes where understanding is hardest:

| Phase | Target Beat Share | Pacing & Goal |
| :--- | :--- | :--- |
| **1. Wide-Angle Hook (Zoom Out)** | ~15% | Brisk opening puzzle or pain point: what breaks without this, and what question are we answering? Skip boilerplate. |
| **2. Core Mechanism Deep-Dive (Zoom In)** | ~55–65% | Slow down. Unpack the 1–3 core difficulties from **at least 2–3 complementary angles** (see below). |
| **3. Synthesis & Bridge (Zoom Out)** | ~20–25% | Lock in the takeaway, show the formal equation/code or contrast with misconceptions, and bridge to the next episode. |

### Mandatory Multi-Angle Rule for Core Concepts
Every core mechanism or difficult formula **must** be unpacked from at least **2–3 angles** in sequence:
1. **Concrete Numerical / Toy Trace**: Walk through 2–3 tiny numbers or one packet/token moving step by step.
2. **Continuous Visual Transformation (Morph / Flow)**: Animate bars morphing into points/curves, data packets traveling along pipes (`mgPacket`), or attention weights shifting—so the viewer *sees* cause and effect rather than reading a static caption.
3. **In-Situ Symbol / Code Alignment**: Reveal the formula or highlighted code line *after* the intuition lands, and tie each piece directly to the visual region.
4. **Counterexample / Boundary Check**: Test an edge value or show why a common beginner guess fails.

---

## 3. Centered, Distraction-Free Stage (No Cluttered PPT Splits!)

When explaining a core point, **the animation owns the center of the `1920×1080` warm alabaster canvas**—no permanent left sidebar, no boxed `.svg-card` borders, and no walls of text competing with the motion:

- **Default to Full-Stage Centered Canvas (`clean_stage=True` + `<canvas class="mg-stage">`)**:
  - Set `clean_stage=True` on core explanation scenes so top progress bars/pills fade away and the viewer sees only the centered visual story + concise bottom cinema subtitle.
  - Let elements **morph and evolve in-place** across beats in one continuous scene (e.g., bars $\rightarrow$ laser cut $\rightarrow$ coordinate dots $\rightarrow$ shifted curve $\rightarrow$ camera zoom + in-situ formula), rather than hard-cutting between isolated text-heavy slides.
- **Assertion-Evidence & Zero Redundancy**:
  - Where a brief framing headline or floating equation (`.float-math`) appears, state a concise **takeaway claim** (`<= 18` chars) and let it **fade out (`data-hide-after`)** before or when the full-stage animation takes over—never keep static bullet lists squatting beside a moving diagram.
  - Keep code tracing in a centered `.code-spotlight` scene (or brief focused beat) with line-by-line `.code-line.hi` spotlighting, never squished into a narrow sidebar.

---

## 4. Narration-first choreography

Write the spoken explanation before animating it. Keep each beat about one idea. A short sentence can identify a token. A longer sentence can follow its projection, travel, and arrival if each operation has a distinct spoken cue. Budget by the recorded duration of the explanation. A count of beats alone gives little indication of how long the audience sees a mechanism.

1. **Establish the subject.** Show the example or the question at the center. Introduce each number when spoken. A neutral opening question gives the viewer something to consider before the first number arrives.
2. **Move during the explanation.** Mark the action words in `Beat.marks`. Guide a move from its start phrase to the next meaningful boundary using `ctx.motion`. In the signal example, the 0.2 bar grows as “0.2” is spoken, the 0.8 bar follows on its own number, and the 1.5 bar gets the remainder of the sentence. When the narrator describes reducing a signal, preserve its original outline long enough to see the amount removed.
3. **Give the result time.** Keep the final position through the pause and the next sentence when they share a subject. After a formula or a substantial transformation, try roughly a second of stillness, then listen in context. A prediction question may need a longer pause.
4. **Review with the actual voice.** Note where the viewer first sees an object, when its movement lands, and which words are spoken at each time. Revisit the frame pair at each sentence boundary. If the same object is still on stage, its held position and opacity should continue through that pair. When attention moves to a new diagram, retire detail from the previous diagram and bring the new one to the center.

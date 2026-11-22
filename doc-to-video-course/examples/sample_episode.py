r"""Gold-standard sample episode demonstrating beginner-first pacing, Assertion-Evidence copy,
declarative focus signaling, and 3-beat anti-transience animations."""
from video_engine import Beat, Episode, Scene


def build_episode() -> Episode:
    sc1 = Scene(
        scene_id="concrete_noise_filter",
        section_label="01 · 先看具体数字：软阈值到底在做什么",
        html=r"""
<div class="studio-split">
  <div class="studio-left">
    <div class="step" data-step="0">
      <div class="eyebrow">Concrete Intuition · 具体算例</div>
      <div class="assertion-title">先忘掉公式：它就像一把带“扣除额”的筛子</div>
    </div>
    <div class="stack" data-focus-group="1">
      <div class="term-chip step" data-step="1" data-focus-id="y0" data-focus-tone="warm">
        <span class="badge warm">弱信号</span>
        <span><b>y₁ = 0.2</b> &rarr; 低于阈值 0.5 &rarr; <b>归零 0.0</b></span>
      </div>
      <div class="term-chip step" data-step="2" data-focus-id="y1">
        <span class="badge blue">中等信号</span>
        <span><b>y₂ = 0.8</b> &rarr; 扣除 0.5 &rarr; <b>保留 0.3</b></span>
      </div>
      <div class="term-chip step" data-step="3" data-focus-id="y2" data-focus-tone="green">
        <span class="badge green">强信号</span>
        <span><b>y₃ = 1.5</b> &rarr; 扣除 0.5 &rarr; <b>保留 1.0</b></span>
      </div>
    </div>
    <div class="callout warn step" data-step="4">
      <b>避坑直觉：</b>不是只砍掉小信号，留下的大信号也要统一减去 λ。
    </div>
  </div>
  <div class="studio-right">
    <div class="svg-card">
      <svg id="bar-svg" viewBox="0 0 680 430"></svg>
      <div class="kv-row" id="bar-kv" style="justify-content:center"></div>
    </div>
  </div>
</div>
""",
        js_frame=r"""
const svg = ctx.sceneEl.querySelector("#bar-svg");
const kv = ctx.sceneEl.querySelector("#bar-kv");
const thr = 0.5;
const vals = [0.2, 0.8, 1.5];
const labels = ["y₁ = 0.2", "y₂ = 0.8", "y₃ = 1.5"];
const activeIdx = ctx.cue.idx === undefined ? -1 : ctx.cue.idx;
const shrinkT = ctx.cue.animate ? easeInOut(ctx.p) : (ctx.cue.done ? 1 : 0);

const f = svgFrame(svg, {
  w: 680, h: 430, pad: { l: 64, r: 30, t: 54, b: 56 },
  x: [0, 3], y: [0, 1.8], nx: 3, ny: 4,
  xlab: false, ylab: true, ydec: 1,
  title: "阈值 λ = 0.5 时，三个观测信号如何被过滤"
});

const baseY = f.sy(0);
for (let i = 0; i < 3; i++) {
  const cx = f.sx(i + 0.5);
  const bw = 72;
  const orig = vals[i];
  const target = Math.max(0, orig - thr);
  let curVal = orig;
  if (i < activeIdx || ctx.cue.allDone) curVal = target;
  else if (i === activeIdx) curVal = svgLerp(orig, target, shrinkT);

  const isFocus = activeIdx === i;
  const hasFocus = activeIdx >= 0;
  const barOp = (!hasFocus || isFocus || ctx.cue.allDone) ? 1 : 0.28;

  // Dashed ghost outline of original height (anti-transience reference)
  const origTop = f.sy(orig);
  svgEl("rect", {
    x: cx - bw / 2, y: origTop, width: bw, height: Math.max(1, baseY - origTop),
    rx: 8, fill: "none", stroke: "rgba(15, 23, 42, 0.28)", "stroke-width": 1.6,
    "stroke-dasharray": "4 4", opacity: barOp
  }, svg);

  // Current filtered bar
  const curTop = f.sy(curVal);
  const barCol = i === 0 ? "#d9483b" : (i === 2 ? "#059669" : "#2563eb");
  if (curVal > 0.01) {
    svgEl("rect", {
      x: cx - bw / 2, y: curTop, width: bw, height: Math.max(1, baseY - curTop),
      rx: 8, fill: barCol, opacity: 0.85 * barOp
    }, svg);
  }
  svgEl("text", {
    x: cx, y: baseY + 26, "text-anchor": "middle",
    fill: isFocus ? "#0f172a" : "#64748b", "font-size": 14.5, "font-weight": 700,
    opacity: barOp, text: labels[i]
  }, svg);
  svgEl("text", {
    x: cx, y: Math.min(origTop, curTop) - 10, "text-anchor": "middle",
    fill: barCol, "font-size": 14.5, "font-weight": 700, class: "mono-txt",
    opacity: barOp, text: curVal.toFixed(2)
  }, svg);
}

// Draw threshold line & badge above the bars so no bar covers the pill
svgEl("line", {
  x1: f.sx(0), x2: f.sx(3), y1: f.sy(thr), y2: f.sy(thr),
  stroke: "#d9483b", "stroke-width": 2, "stroke-dasharray": "6 5"
}, svg);
svgBadgePill(svg, f.sx(0.5), f.sy(thr) - 24, "阈值 λ = 0.5", {
  bg: "#fff1f2", fg: "#be123c", stroke: "#d9483b", fontSize: 12.5
});

kv.innerHTML =
  '<span class="kv">原值 <b>[0.2, 0.8, 1.5]</b></span>' +
  '<span class="kv warn">阈值 λ = <b>0.5</b></span>' +
  '<span class="kv green">输出 <b>[0.0, 0.3, 1.0]</b></span>';
""",
        beats=[
            Beat(
                sub="先别急着背公式：假设我们测到三个信号 0.2、0.8 和 1.5，把过滤阈值设为 0.5。",
                tts="先别急着背公式：假设我们测到三个信号，0.2、0.8 和 1.5，把过滤阈值设为 0.5。",
                cue={"step": 0, "idx": -1},
                pause_after=0.45,
            ),
            Beat(
                sub="第一个弱信号 0.2 没过 0.5 的门槛，为了去噪，它被整根压成 0。",
                tts="第一个弱信号 0.2 没过 0.5 的门槛，为了去噪，它被整根压成 0。",
                cue={"step": 1, "focus": "y0", "idx": 0, "animate": True},
                continuous=True,
                pause_after=0.4,
            ),
            Beat(
                sub="第二个信号 0.8 跨过了门槛，但注意看虚线框：它不是原样保留，而是扣掉 0.5 剩下 0.3。",
                tts="第二个信号 0.8 跨过了门槛，但注意看虚线框：它不是原样保留，而是扣掉 0.5 剩下 0.3。",
                cue={"step": 2, "focus": "y1", "idx": 1, "animate": True},
                continuous=True,
                pause_after=0.4,
            ),
            Beat(
                sub="第三个强信号 1.5 同样扣除 0.5，剩下 1.0，依然是主导信号。",
                tts="第三个强信号 1.5 同样扣除 0.5，剩下 1.0，依然是主导信号。",
                cue={"step": 3, "focus": "y2", "idx": 2, "animate": True},
                continuous=True,
                pause_after=0.5,
            ),
            Beat(
                sub="记住这个直觉：小于 λ 的全部清零，大于 λ 的也要整体缩水 λ。",
                tts="记住这个直觉：小于 lambda 的全部清零，大于 lambda 的也要整体缩水 lambda。",
                cue={"step": 4, "allDone": True},
                pause_after=1.0,
            ),
        ],
    )

    sc2 = Scene(
        scene_id="visual_to_formula_and_code",
        section_label="02 · 从图像到公式与代码：为什么化作 ReLU(y − λ)",
        html=r"""
<div class="studio-split">
  <div class="studio-left">
    <div class="step" data-step="0">
      <div class="eyebrow">Pictorial &rarr; Abstract · 图景转符号</div>
      <div class="assertion-title">阈值 λ 越大，曲线越向右平移，零区越宽</div>
    </div>
    <div class="math-stage step" data-step="2">
      $$a^\star = \operatorname{ReLU}(y - \lambda) = \max(y - \lambda, 0)$$
    </div>
    <div class="code-window step" data-step="3">
      <div class="code-chrome">
        <div class="win-dots"><span></span><span></span><span></span></div>
        <span class="win-title">soft_threshold.py</span>
      </div>
      <pre class="code" id="sample-code"><span class="code-line" data-ln="0">def soft_relu(y, lambd):</span><span class="code-line" data-ln="1">    return np.maximum(y - lambd, 0.0)</span></pre>
    </div>
    <div class="callout step" data-step="4">
      <b>对应关系：</b>向左/下平移 λ 后再对 0 取截断，拐点恰好落在 <b>y = λ</b>。
    </div>
  </div>
  <div class="studio-right">
    <div class="svg-card">
      <svg id="curve-svg" viewBox="0 0 680 430"></svg>
      <div class="kv-row" id="curve-kv" style="justify-content:center"></div>
    </div>
  </div>
</div>
""",
        js_frame=r"""
const svg = ctx.sceneEl.querySelector("#curve-svg");
const kv = ctx.sceneEl.querySelector("#curve-kv");
const ln = ctx.cue.line;
ctx.sceneEl.querySelectorAll("#sample-code .code-line").forEach((el) => {
  el.classList.toggle("hi", ln !== undefined && parseInt(el.getAttribute("data-ln"), 10) === ln);
});

const thr = ctx.cue.sweep ? 0.65 * easeInOut(ctx.p) : (ctx.cue.thr !== undefined ? ctx.cue.thr : 0.0);
const f = svgFrame(svg, {
  w: 680, h: 430, pad: { l: 64, r: 28, t: 50, b: 48 },
  x: [-0.3, 1.5], y: [-0.1, 1.4], nx: 6, ny: 5,
  xlab: true, ylab: true, xdec: 1, ydec: 1,
  title: "虚线基准 λ=0 vs 实线当前 λ=" + thr.toFixed(2)
});

// Ghost reference baseline (lambda = 0) so viewer sees the shift clearly
const ghostPts = [];
const curPts = [];
for (let y = -0.3; y <= 1.501; y += 0.03) {
  ghostPts.push([f.sx(y), f.sy(Math.max(0, y))]);
  curPts.push([f.sx(y), f.sy(Math.max(0, y - thr))]);
}
svgPolyline(svg, ghostPts, "rgba(100, 116, 139, 0.45)", 2.2, "6 5");
svgAreaPolyline(svg, curPts, "#d9483b", "grad-red", f.sy(0));

svgEl("line", {
  x1: f.sx(thr), x2: f.sx(thr), y1: f.sy(0), y2: f.sy(thr + 0.34),
  stroke: "#2563eb", "stroke-width": 2, "stroke-dasharray": "5 4"
}, svg);
svgDot(svg, f.sx(thr), f.sy(0), "#2563eb", 6.5, true);
svgBadgePill(svg, f.sx(thr), f.sy(thr + 0.40), "拐点 y = " + thr.toFixed(2), {
  bg: "#eff6ff", fg: "#1e40af", stroke: "#2563eb", fontSize: 13, mono: true
});

kv.innerHTML =
  '<span class="kv">基准 <b>λ = 0</b></span>' +
  '<span class="kv warn">当前阈值 λ = <b>' + thr.toFixed(2) + '</b></span>';
""",
        beats=[
            Beat(
                sub="把刚才的三根柱子画成连续曲线：先看虚线基准，当 λ 为 0 时，所有正数都原样输出。",
                tts="把刚才的三根柱子画成连续曲线：先看虚线基准，当 lambda 为 0 时，所有正数都原样输出。",
                cue={"step": 0, "thr": 0.0, "sweep": False},
                pause_after=0.5,
            ),
            Beat(
                sub="现在让阈值 λ 慢慢增大到 0.65，注意红线相对虚线整体向右平移，贴地归零的区间不断变宽。",
                tts="现在让阈值 lambda 慢慢增大到 0.65，注意红线相对虚线整体向右平移，贴地归零的区间不断变宽。",
                cue={"step": 1, "sweep": True},
                continuous=True,
                pause_after=1.0,
            ),
            Beat(
                sub="这种“先减 λ、再把负数压成 0”的形状，写进数学就是 ReLU(y − λ) = max(y − λ, 0)。",
                tts="这种先减 lambda、再把负数压成 0 的形状，写进数学就是 R e L U of y 减 lambda，等于 max y 减 lambda 与 0。",
                cue={"step": 2, "thr": 0.65, "sweep": False},
                pause_after=0.85,
            ),
            Beat(
                sub="落到 NumPy 代码也只有这一行：y 减去阈值之后，对 0.0 取逐元素最大值。",
                tts="落到 NumPy 代码也只有这一行：y 减去阈值之后，对 0.0 取逐元素最大值。",
                cue={"step": 3, "line": 1, "thr": 0.65, "sweep": False},
                pause_after=0.45,
            ),
            Beat(
                sub="所以别被“近端映射”这个名字吓到，它本质上就是带平移阈值的 ReLU 截断。",
                tts="所以别被近端映射这个名字吓到，它本质上就是带平移阈值的 R e L U 截断。",
                cue={"step": 4, "line": 1, "thr": 0.65, "sweep": False},
                pause_after=0.9,
            ),
        ],
    )

    return Episode(
        ep_num="00",
        title="软阈值与 ReLU：从具体直觉到公式",
        subtitle="Doc-to-Video Keynote Studio",
        filename="00_sample_demo.mp4",
        scenes=[sc1, sc2],
    )

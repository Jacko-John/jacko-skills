"""Minimal runnable example episode demonstrating Modern Keynote Studio primitives."""
from video_engine import Beat, Episode, Scene


def build_episode() -> Episode:
    sc1 = Scene(
        scene_id="demo_soft_threshold",
        section_label="01 · 软阈值与 ReLU 演示样例",
        html="""
<div class="studio-split">
  <div class="studio-left">
    <div class="step" data-step="0">
      <div class="eyebrow">Proximal Operator · 近端映射</div>
      <div class="k-title">为什么 L1 正则化会化作 ReLU？</div>
      <div class="math-stage" style="margin-top:14px;">
        $$a^\\star = \\operatorname{ReLU}(y - \\lambda) = \\max(y - \\lambda, 0)$$
      </div>
    </div>
    <div class="note-block step" data-step="0" data-dim-past="1">
      <div class="note-title">1. 几何截断效应</div>
      <p>当惩罚阈值 $\\lambda$ 增大时，小于 $\\lambda$ 的分量被直接压成 0，只保留显著信号。</p>
    </div>
    <div class="code-window step" data-step="1">
      <div class="code-chrome">
        <div class="win-dots"><span></span><span></span><span></span></div>
        <span class="win-title">ista_step.py</span>
      </div>
      <pre class="code" id="sample-code"><span class="code-line" data-ln="0">def soft_relu(y, lambd):</span><span class="code-line" data-ln="1">    return np.maximum(y - lambd, 0.0)</span></pre>
    </div>
  </div>
  <div class="studio-right">
    <div class="svg-card">
      <svg id="sample-svg" viewBox="0 0 680 420"></svg>
      <div class="kv-row" id="sample-kv" style="justify-content:center"></div>
    </div>
  </div>
</div>
""",
        js_frame="""
const svg = ctx.sceneEl.querySelector("#sample-svg");
const kv = ctx.sceneEl.querySelector("#sample-kv");
const ln = ctx.cue.line;
ctx.sceneEl.querySelectorAll("#sample-code .code-line").forEach((el) => {
  el.classList.toggle("hi", ln !== undefined && parseInt(el.getAttribute("data-ln"), 10) === ln);
});
const thr = ctx.cue.sweep ? 0.8 * easeInOut(ctx.p) : 0.4;
const f = svgFrame(svg, {
  w: 680, h: 420, pad: { l: 64, r: 28, t: 48, b: 46 },
  x: [-0.5, 1.5], y: [-0.1, 1.3], nx: 4, ny: 4,
  xlab: true, ylab: true, xdec: 1, ydec: 1,
  title: "ReLU(y − λ) 曲线（当前 λ = " + thr.toFixed(2) + "）"
});
const pts = [];
for (let y = -0.5; y <= 1.5; y += 0.05) {
  pts.push([f.sx(y), f.sy(Math.max(0, y - thr))]);
}
svgAreaPolyline(svg, pts, "#d9483b", "grad-red", f.sy(0));
svgEl("line", { x1: f.sx(thr), x2: f.sx(thr), y1: f.sy(0), y2: f.sy(1.1), stroke: "#2563eb", "stroke-width": 2, "stroke-dasharray": "5 4" }, svg);
svgCalloutArrow(svg, f.sx(thr) - 90, f.sy(0.55), f.sx(thr), f.sy(0.03), "阈值拐点 λ=" + thr.toFixed(2), "blue", "#2563eb", "middle");
kv.innerHTML = '<span class="kv">阈值 λ = <b>' + thr.toFixed(2) + '</b></span>';
""",
        beats=[
            Beat(
                sub="这是一个现代 Keynote 风格样例：当阈值 λ 逐步增大，阴影区域整体向右平移。",
                tts="这是一个现代 Keynote 风格样例：当阈值 lambda 逐步增大，阴影区域整体向右平移。",
                cue={"step": 0, "sweep": True},
                continuous=True,
            ),
            Beat(
                sub="写成代码只有一行：对 y 减去阈值后再对 0 取最大值，就是非负稀疏投影。",
                tts="写成代码只有一行：对 y 减去阈值后再对 0 取最大值，就是非负稀疏投影。",
                cue={"step": 1, "line": 1, "sweep": False},
            ),
        ],
    )
    return Episode(
        ep_num="00",
        title="示例小节",
        subtitle="Doc-to-Video Keynote Studio",
        filename="00_sample_demo.mp4",
        scenes=[sc1],
    )

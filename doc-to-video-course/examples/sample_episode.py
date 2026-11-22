r"""Three signals become a threshold curve, then one NumPy expression."""
from video_engine import Beat, Episode, Scene


def build_episode() -> Episode:
    sc1 = Scene(
        scene_id="centered_soft_threshold_story",
        section_label="01 · 从三个信号到 ReLU(y − λ)",
        clean_stage=True,
        html=r"""<canvas class="mg-stage" id="mg-relu" width="1920" height="1080"></canvas>""",
        js_frame=r"""
const canvas = ctx.sceneEl.querySelector("#mg-relu");
const c = canvas.getContext("2d");
mgClear(c);

const motion = ctx.motion;
const vals = [0.2, 0.8, 1.5];
const barCols = ["#d9483b", "#2563eb", "#059669"];

const barIn = [
  easeOutQuart(ctx.snap(0, "v1", 0.24)),
  easeOutQuart(ctx.snap(0, "v2", 0.24)),
  easeOutQuart(ctx.snap(0, "v3", 0.24)),
];
const laserSweep = easeOutQuart(ctx.snap(1, "gate", 0.30));
const shrinkSmall = easeOutQuart(ctx.snap(1, "zero", 0.26));
const shrinkLarge = easeWhip(ctx.motion(1, "cut", null));
const shrink = [shrinkSmall, shrinkLarge, shrinkLarge];
const morphT = easeWhip(motion(2, "input", "base"));
const ghostDraw = easeOutQuart(motion(2, "base", "shift"));
const lamSweep = easeWhip(motion(2, "shift", null));
const lam = 0.5 * lamSweep;
const kinkFocus = ctx.snap(3, "kink", 0.26);
const formulaIn = ctx.snap(3, "relu", 0.28);
const toCode = easeWhip(motion(3, "minus", null));

const bounds = { x: 400, y: 210, w: 1140, h: 550, xmin: -0.3, xmax: 1.8, ymin: 0, ymax: 1.8 };
const sx = (v) => bounds.x + ((v - bounds.xmin) / (bounds.xmax - bounds.xmin)) * bounds.w;
const sy = (v) => bounds.y + bounds.h - ((v - bounds.ymin) / (bounds.ymax - bounds.ymin)) * bounds.h;
const baseY = sy(0);
const barX0 = [620, 960, 1300];

c.save();
c.globalAlpha = 1 - toCode;
const promptAlpha = 1 - easeInOut(motion(0, "signals", "v1"));
if (promptAlpha > 0.01) {
  mgPill(c, 960, 480, "CONCRETE INTUITION · 三个信号经过门槛会留下多少？", {
    bg: "rgba(255,255,255,0.96)", fg: "#1e40af", stroke: "#2563eb", h: 52, padX: 40,
    font: "700 24px -apple-system, 'PingFang SC', sans-serif",
    alpha: (1 - toCode) * promptAlpha,
  });
}
c.save();
c.globalAlpha *= (1 - morphT) * (1 - promptAlpha);
c.strokeStyle = "rgba(15, 23, 42, 0.20)";
c.lineWidth = 2;
c.beginPath();
c.moveTo(460, baseY);
c.lineTo(1460, baseY);
c.stroke();
c.restore();
mgAxes(c, bounds, {
  yTicks: [0.5, 1.0, 1.5], xTicks: [0, 0.5, 1.0, 1.5],
  xLabel: "y", alpha: morphT,
});

const laserAlpha = laserSweep * (1 - morphT);
if (laserAlpha > 0.01) {
  c.save();
  c.globalAlpha *= laserAlpha;
  c.strokeStyle = "#d9483b";
  c.lineWidth = 3;
  c.setLineDash([12, 9]);
  c.beginPath();
  c.moveTo(460, sy(0.5));
  c.lineTo(lerp(460, 1420, laserSweep), sy(0.5));
  c.stroke();
  c.restore();
  if (laserSweep > 0.55) {
    mgPill(c, 1520, sy(0.5), "门槛 λ = 0.5", {
      bg: "#fff1f2", stroke: "#d9483b", fg: "#be123c",
      alpha: laserAlpha * subP(laserSweep, 0.55, 0.95),
    });
  }
}

for (let i = 0; i < 3; i++) {
  const enter = barIn[i];
  if (enter <= 0.01) continue;
  const orig = vals[i];
  const target = Math.max(0, orig - 0.5);
  const output = lerp(orig, target, shrink[i]);
  const curVal = output * enter;
  const cx = lerp(barX0[i], sx(orig), morphT);
  const bw = lerp(124, 18, morphT);
  const col = barCols[i];

  const ghostAlpha = (1 - morphT) * subP(shrink[i], 0, 0.25);
  if (ghostAlpha > 0.01) {
    c.save();
    c.globalAlpha *= ghostAlpha * 0.55;
    c.strokeStyle = "rgba(15, 23, 42, 0.35)";
    c.lineWidth = 2;
    c.setLineDash([7, 6]);
    mgRoundRect(c, cx - bw / 2, sy(orig), bw, baseY - sy(orig), 14);
    c.stroke();
    c.restore();

    if (i > 0 && shrink[i] > 0.65) {
      c.save();
      c.globalAlpha *= ghostAlpha * subP(shrink[i], 0.65, 1.0);
      c.fillStyle = "#d9483b";
      c.font = "700 20px ui-monospace, SFMono-Regular, monospace";
      c.textAlign = "center";
      c.textBaseline = "middle";
      c.fillText("−0.5", cx, (sy(orig) + sy(target)) / 2);
      c.restore();
    }
  }

  if (morphT < 0.98) {
    const barH = Math.max(0, baseY - sy(curVal));
    if (barH > 2) {
      c.save();
      c.globalAlpha *= (1 - morphT) * 0.92;
      const grad = c.createLinearGradient(0, sy(curVal), 0, baseY);
      grad.addColorStop(0, col);
      grad.addColorStop(1, col + "cc");
      c.fillStyle = grad;
      c.shadowColor = col + "33";
      c.shadowBlur = 18;
      c.shadowOffsetY = 6;
      mgRoundRect(c, cx - bw / 2, sy(curVal), bw, barH, 14);
      c.fill();
      c.restore();
    }
  }

  if (morphT > 0.05) {
    c.save();
    c.globalAlpha *= morphT;
    mgDot(c, cx, sy(target), col, lerp(20, 9.5, morphT), true);
    c.restore();
  }

  const labelAlpha = enter * clamp(1 - morphT * 1.4, 0, 1);
  if (labelAlpha > 0.02) {
    const labelY = sy(orig * enter) - 14;
    c.save();
    c.globalAlpha *= labelAlpha;
    c.fillStyle = col;
    c.font = "700 28px ui-monospace, SFMono-Regular, monospace";
    c.textAlign = "center";
    c.textBaseline = "bottom";
    c.fillText(output.toFixed(1), cx, labelY);
    c.fillStyle = "#475569";
    c.font = "600 21px -apple-system, 'PingFang SC', sans-serif";
    c.textBaseline = "top";
    c.fillText("信号 " + orig.toFixed(1), cx, baseY + 18);
    c.restore();
  }
}

if (ghostDraw > 0.01) {
  mgCurve(c, sx, sy, (x) => Math.max(0, x), -0.3, 1.8, {
    progress: ghostDraw,
    color: "rgba(100, 116, 139, 0.55)",
    lw: 3,
    dash: [10, 8],
  });
  if (ghostDraw > 0.7) {
    c.save();
    c.globalAlpha *= subP(ghostDraw, 0.7, 1.0);
    c.fillStyle = "#64748b";
    c.font = "700 19px -apple-system, 'PingFang SC', sans-serif";
    c.textAlign = "right";
    c.textBaseline = "bottom";
    c.fillText("λ = 0 基准", sx(1.22), sy(1.30));
    c.restore();
  }

  const curveAlpha = subP(lamSweep, 0.0, 0.18);
  if (curveAlpha > 0.01) {
    const areaG = c.createLinearGradient(0, sy(1.3), 0, baseY);
    areaG.addColorStop(0, "rgba(37, 99, 235, 0.16)");
    areaG.addColorStop(1, "rgba(37, 99, 235, 0.01)");
    mgCurve(c, sx, sy, (x) => Math.max(0, x - lam), -0.3, 1.8, {
      color: "#2563eb",
      lw: 4.8,
      fill: areaG,
      baseY: baseY,
      alpha: curveAlpha,
    });

    if (lam > 0.06) {
      const shiftAlpha = subP(lam, 0.06, 0.25);
      mgArrow(c, sx(0.02), baseY - 26, sx(lam - 0.02), baseY - 26, {
        color: "#d97706", lw: 3, alpha: shiftAlpha,
      });
      c.save();
      c.globalAlpha *= shiftAlpha;
      c.fillStyle = "#b45309";
      c.font = "700 19px ui-monospace, 'PingFang SC', sans-serif";
      c.textAlign = "center";
      c.textBaseline = "bottom";
      c.fillText("右移 λ = " + lam.toFixed(2), (sx(0) + sx(lam)) / 2, baseY - 38);
      c.restore();
    }

    if (lam > 0.02) {
      mgDot(c, sx(lam), baseY, "#d97706", lerp(8.5, 15, kinkFocus), true);
    }
  }
}

c.restore();

if (formulaIn > 0) {
  const fx = lerp(sx(0.28), 960, toCode);
  const fy = lerp(sy(1.22), 465, toCode);
  mgArrow(c, fx + 34, fy + 44, sx(0.5) - 10, baseY - 22, {
    color: "#2563eb", lw: 2.5, progress: formulaIn, alpha: formulaIn * (1 - toCode),
  });
  mgFormula(c, fx, fy, "ReLU(y − λ) = max(y − λ, 0)", { alpha: formulaIn });
}
""",
        beats=[
            Beat(
                sub="先别急着背公式。假设系统刚收到三个信号：0.2、0.8 和 1.5。",
                tts="先别急着背公式。假设系统刚收到三个信号：0.2、0.8 和 1.5。",
                cue={"step": 0},
                marks={"signals": "三个信号", "v1": "0.2", "v2": "0.8", "v3": "1.5"},
                continuous=True,
                pause_after=0.45,
            ),
            Beat(
                sub="设一道门槛 λ = 0.5：低于门槛的直接清零，跨过去的也要扣掉 0.5。",
                tts="设一道门槛 lambda 等于 0.5：低于门槛的直接清零，跨过去的也要扣掉 0.5。",
                cue={"step": 1},
                marks={"gate": "门槛", "low": "低于", "zero": "清零", "cross": "跨过去", "cut": "扣掉"},
                continuous=True,
                pause_after=0.65,
            ),
            Beat(
                sub="把所有可能输入排成横轴：原本原样通过的虚线，被整体向右推了 λ。",
                tts="把所有可能输入排成横轴：原本原样通过的虚线，被整体向右推了 lambda。",
                cue={"step": 2},
                marks={"input": "输入", "base": "原本", "shift": "向右推"},
                continuous=True,
                pause_after=0.75,
            ),
            Beat(
                sub="这根在 λ 处才抬头的折线，其实就是向右平移后的 ReLU(y − λ)。",
                tts="这根在 lambda 处才抬头的折线，其实就是向右平移后的 R e L U of y 减 lambda。",
                cue={"step": 3},
                marks={"kink": "抬头", "relu": "R e L U", "minus": "减 lambda"},
                continuous=True,
                pause_after=1.00,
            ),
        ],
    )

    sc2 = Scene(
        scene_id="centered_code_spotlight",
        section_label="02 · 落到代码只需一行",
        clean_stage=True,
        html=r"""<canvas class="mg-stage" id="mg-code" width="1920" height="1080"></canvas>""",
        js_frame=r"""
const c = ctx.sceneEl.querySelector("#mg-code").getContext("2d");
mgClear(c);

// The opening formula occupies the same position as the previous scene's last frame.
const handoff = easeWhip(ctx.motion(0, "numpy", "subtract"));
const subtract = easeOutQuart(ctx.snap(0, "subtract", 0.22));
const maximum = easeOutQuart(ctx.snap(0, "clamp", 0.22));
const example = ctx.snap(1, "strong", 0.26);
const result = easeOutQuart(ctx.snap(1, "deduct", 0.28));
const keepGraph = ctx.snap(1, "graph", 0.24);

mgFormula(c, 960, 465, "ReLU(y − λ) = max(y − λ, 0)", { alpha: 1 - handoff });

if (handoff > 0.01) {
  c.save();
  c.globalAlpha = handoff;
  const liftY = lerp(0, -35, example);
  mgHeader(c, 960, 215 + liftY, "CODE SPOTLIGHT · 软阈值一行实现", "先统一扣除门槛 λ，再对 0 取最大值");

  const hl1 = subtract * (1 - maximum);
  const hl2 = maximum * (1 - keepGraph);
  mgCodeWindow(c, 410, 290 + liftY, 1100, 265, {
    filename: "soft_threshold.py",
    commentOffset: 620,
    lines: [
      { code: "shifted = y - lambd", comment: "# 强信号也要先减去门槛 λ", highlight: hl1, alpha: 0.35 + 0.65 * subtract },
      { code: "out = np.maximum(shifted, 0.0)", comment: "# 低于门槛的负值统一归零", highlight: hl2, alpha: 0.35 + 0.65 * maximum },
      { code: "return out", comment: "# 保证大信号曲线连续平滑", highlight: keepGraph, alpha: 0.35 + 0.65 * maximum },
    ],
  });
  c.restore();
}

if (example > 0.01) {
  const popIn = mgPop(example);
  const resPop = mgPop(result);
  mgNode(c, 450, 595 + popIn.yOff, 290, 108, "强信号 y = 1.5", "必须先统一扣除 λ", {
    state: "active", alpha: popIn.alpha, scale: popIn.scale,
    titleFont: "700 24px -apple-system, 'PingFang SC', sans-serif",
    subFont: "500 17px -apple-system, 'PingFang SC', sans-serif",
  });
  mgArrow(c, 748, 649, 868, 649, {
    progress: result, color: "#2563eb", lw: 3.2, label: "− λ (0.5)",
  });
  mgNode(c, 876, 595 + resPop.yOff, 290, 108, "保留输出 = 1.0", "图像连续无断崖", {
    state: "green", alpha: resPop.alpha, scale: resPop.scale,
    titleFont: "700 24px -apple-system, 'PingFang SC', sans-serif",
    subFont: "500 17px -apple-system, 'PingFang SC', sans-serif",
  });
  mgPill(c, 1345, 649, "弱信号 0.2 − 0.5 < 0 → 归零 0.0", {
    bg: "#fff1f2", fg: "#be123c", stroke: "#d9483b", h: 44, padX: 26,
    font: "700 18px -apple-system, 'PingFang SC', sans-serif",
    alpha: keepGraph,
  });
}
""",
        beats=[
            Beat(
                sub="所以别被“近端映射”吓到，写成 NumPy 代码就是先减 λ、再对 0 取最大值。",
                tts="所以别被近端映射吓到，写成 NumPy 代码就是先减 lambda、再对 0 取最大值。",
                marks={"numpy": "NumPy", "subtract": "先减", "clamp": "再对"},
                continuous=True,
                pause_after=0.45,
            ),
            Beat(
                sub="记住唯一避坑点：大于 λ 的强信号也必须减去 λ，才能和图像保持连续。",
                tts="记住唯一避坑点：大于 lambda 的强信号也必须减去 lambda，才能和图像保持连续。",
                marks={"strong": "强信号", "deduct": "减去", "graph": "图像"},
                continuous=True,
                pause_after=0.95,
            ),
        ],
    )

    return Episode(
        ep_num="00",
        title="软阈值与 ReLU：从直觉到一行代码",
        subtitle="Doc-to-Video Warm Alabaster Studio",
        filename="00_sample_demo.mp4",
        scenes=[sc1, sc2],
    )

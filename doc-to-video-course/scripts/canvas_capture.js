// The browser paints all CSS. Only a full-size, unstyled canvas can be added
// directly to a cached screenshot of the surrounding page.
function createCanvasCapture() {
  const shell = document.querySelector(".frame-shell");
  const stage = shell.querySelector("main");
  const topbar = shell.querySelector(".topbar");
  const subtitle = shell.querySelector(".subtitle-wrap");
  const box = subtitle.querySelector(".subtitle-box");
  const probe = document.createElement("canvas");
  const probeCtx = probe.getContext("2d", {willReadFrequently: true});
  const width = 1920, height = 1080;
  let shellChanged = true;
  const observer = new MutationObserver(invalidate);

  function invalidate(records) {
    for (const record of records) {
      const el = record.target;
      // The engine rewrites these even when seeking inside the same sentence.
      if (el.closest?.(".topbar") || (el === box && record.type === "childList")) continue;
      if (record.type === "attributes" && record.oldValue === el.getAttribute(record.attributeName)) continue;
      shellChanged = true;
    }
  }
  observer.observe(document.documentElement, {
    attributes: true, attributeOldValue: true, childList: true, subtree: true, characterData: true
  });

  function plan(frame) {
    invalidate(observer.takeRecords());
    const scene = document.getElementById("scene-" + frame.sceneId);
    if (!probeCtx || !shell.classList.contains("clean-mode") || getComputedStyle(topbar).opacity !== "0") return null;
    // User styles can add paint outside element boxes, including pseudo-elements.
    if (document.querySelector("style:not(#course-stage-css), link[rel=stylesheet]:not(#course-math-css)") ||
        document.adoptedStyleSheets?.length || document.getAnimations().length) return null;
    for (const el of document.body.children) {
      if (el !== shell && el.getBoundingClientRect().width &&
          el.getBoundingClientRect().height && getComputedStyle(el).display !== "none") return null;
    }
    for (const el of stage.children) {
      if (el !== scene && getComputedStyle(el).display !== "none") return null;
    }
    for (const el of shell.children) {
      if (el !== topbar && el !== stage && el !== subtitle && getComputedStyle(el).display !== "none") return null;
    }
    let canvas = null;
    for (const node of scene.childNodes) {
      if (node.nodeType === Node.TEXT_NODE && node.textContent.trim()) return null;
      if (node.nodeType !== Node.ELEMENT_NODE) continue;
      if (getComputedStyle(node).display === "none") continue;
      if (canvas || !node.matches("canvas.mg-stage")) return null;
      canvas = node;
    }
    if (!canvas || canvas.className !== "mg-stage" || canvas.hasAttribute("style") ||
        canvas.width !== width || canvas.height !== height ||
        canvas.getAttributeNames().some(name => name.startsWith("data-"))) return null;
    if (scene.className !== "scene active" || stage.className !== "stage" ||
        shell.className !== "frame-shell clean-mode" ||
        [scene, stage, shell, document.body, document.documentElement].some(el => el.hasAttribute("style"))) return null;
    const style = getComputedStyle(canvas);
    if (style.opacity !== "1" || style.visibility !== "visible" || style.transform !== "none" ||
        style.filter !== "none" || style.mixBlendMode !== "normal") return null;
    const rect = canvas.getBoundingClientRect();
    if (rect.x !== 0 || rect.y !== 0 || rect.width !== width || rect.height !== height) return null;

    const dirty = shellChanged;
    shellChanged = false;
    let clip = null;
    if (frame.sub) {
      const r = box.getBoundingClientRect();
      // Include the native subtitle shadow and the input area for its 18px
      // backdrop blur. The standard stylesheet is required by the checks above.
      const x = Math.max(0, Math.floor(r.left - 100));
      const y = Math.max(0, Math.floor(r.top - 100));
      const w = Math.min(width, Math.ceil(r.right + 100)) - x;
      const h = Math.min(height, Math.ceil(r.bottom + 100)) - y;
      if (w > 0 && h > 0) clip = {x, y, width: w, height: h};
    }
    // Reading one pixel also checks origin cleanliness on frames with no subtitle.
    const area = clip || {x: 0, y: 0, width: 1, height: 1};
    const {x, y, width: w, height: h} = area;
    if (probe.width !== w) probe.width = w;
    if (probe.height !== h) probe.height = h;
    probeCtx.clearRect(0, 0, w, h);
    probeCtx.drawImage(canvas, x, y, w, h, 0, 0, w, h);
    try {
      const pixels = probeCtx.getImageData(0, 0, w, h).data;
      if (clip && !new Uint32Array(pixels.buffer).some(pixel => pixel !== 0)) clip = null;
    } catch (error) {
      if (error.name !== "SecurityError") throw error;
      // Native page captures also work for a canvas with cross-origin content.
      probe.width = w;
      return null;
    }
    return {canvas, dirty, clip};
  }

  // Screenshot style injection temporarily mutates document.head. Discard only
  // the observer records produced during capture, before the next author frame.
  return {plan, didCapture() { observer.takeRecords(); shellChanged = false; }};
}

// Both encoders consume this composition. CSS styling and font shaping are
// rasterized by the same browser that renders the preflight page.
function createFrameCompositor() {
  const capture = createCanvasCapture();
  const plate = new Image(), shot = new Image();
  const canvas = document.createElement("canvas");
  canvas.width = 1920;
  canvas.height = 1080;
  const c = canvas.getContext("2d", {alpha: false});
  let plan, plateKey;

  function composite() {
    c.drawImage(plate, 0, 0);
    c.drawImage(plan.canvas, 0, 0);
    return plan.clip ? {kind: "clip", clip: plan.clip} : null;
  }

  function prepare(frame) {
    window.seekToState(frame);
    plan = capture.plan(frame);
    if (!plan) {
      plateKey = null;
      return {kind: "page"};
    }
    const key = JSON.stringify([frame.sceneIdx, frame.sub]);
    if (plan.dirty || plateKey !== key) {
      plateKey = key;
      return {kind: "plate"};
    }
    return composite();
  }

  async function supply({kind, png}) {
    const img = kind === "plate" ? plate : shot;
    img.src = "data:image/png;base64," + png;
    await img.decode();
    if (kind === "plate") {
      capture.didCapture();
      return composite();
    }
    const {x, y} = kind === "clip" ? plan.clip : {x: 0, y: 0};
    c.drawImage(img, x, y);
    return null;
  }

  return {canvas, prepare, supply};
}

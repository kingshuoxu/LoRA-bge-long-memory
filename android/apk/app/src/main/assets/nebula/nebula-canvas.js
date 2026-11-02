import { classifyField } from "./nebula-pixels.js";

// WebGL 画面被判成格子，或上下文起不来时，在同一页用 canvas 画软粒子云。
// 专家标签仍是 HTML，点选仍走原来的事实卡。不换 Compose 那条没有这些标签的路径。

const COLORS = [
  [255, 92, 54],
  [46, 214, 196],
  [255, 196, 72],
  [154, 86, 255],
  [255, 96, 122],
  [78, 132, 255],
];

function mulberry32(seed) {
  let state = seed >>> 0;
  return function next() {
    state = (state + 0x6D2B79F5) >>> 0;
    let value = state;
    value = Math.imul(value ^ (value >>> 15), value | 1);
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
}

function e2ePage() {
  return /(?:\?|&)e2e=1(?:&|$)/.test(String(location.search || ""));
}

export function createCanvasNebula(canvas, hooks) {
  const ctx = canvas.getContext("2d", { alpha: false });
  if (!ctx) throw new Error("canvas2d missing");
  const e2eShot = e2ePage();
  let experts = [];
  let facts = [];
  let nodes = [];
  let stars = [];
  let links = [];
  let labels = [];
  let labelLayer = null;
  let camX = 0;
  let camY = 0;
  let camZ = 28;
  let mode = "full";
  let running = true;
  let frameCount = 0;
  let touches = 0;
  let probed = false;
  let probe = { flip: 0, peak: 0, rough: 0, lattice: false, variance: 0 };
  let canvasVariance = 0;
  let canvasDiff = 0;
  let canvasMoved = 0;
  let capturedBefore = false;
  let beforeLumas = null;
  let gestureAt = 0;
  let lastSampleAt = 0;
  let recallName = "";
  const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function ensureLabels() {
    const host = canvas.parentElement;
    if (!host) return null;
    if (!labelLayer || labelLayer.parentElement !== host) {
      labelLayer = document.createElement("div");
      labelLayer.className = "nebula-labels";
      host.appendChild(labelLayer);
    }
    return labelLayer;
  }

  function project(x, y) {
    const width = canvas.clientWidth || 1;
    const height = canvas.clientHeight || 1;
    const f = (height * 0.42) / Math.max(8, camZ);
    return {
      x: width / 2 + (x - camX) * f,
      y: height / 2 - (y - camY) * f,
      f,
    };
  }

  function fillLabel(item) {
    let name = (item.expert && (item.expert.display_name || item.expert.name)) || "";
    if (window.i18n && window.i18n.getLocale() === "en" && window.i18n.foreignName) name = window.i18n.foreignName(name);
    const countText = window.i18n && window.i18n.t ? window.i18n.t("nebula.count", { n: item.count }) : String(item.count);
    item.el.querySelector(".name").textContent = name;
    item.el.querySelector(".meta").textContent = ` · ${countText}`;
    const tag = item.el.querySelector(".tag");
    if (item.fresh) {
      const word = window.i18n && window.i18n.t ? window.i18n.t("nebula.new") : "新";
      tag.hidden = false;
      tag.textContent = ` · ${word}`;
    } else {
      tag.hidden = true;
      tag.textContent = "";
    }
  }

  function placeLabels() {
    const width = canvas.clientWidth || 1;
    const height = canvas.clientHeight || 1;
    labels.forEach((item) => {
      const p = project(item.x, item.y);
      const hw = Math.max(36, item.el.offsetWidth / 2);
      const hh = Math.max(14, item.el.offsetHeight / 2);
      let x = p.x;
      let y = p.y - Math.max(36, 18 * p.f) - hh;
      if (y < 28 + hh) y = p.y + Math.max(36, 18 * p.f) + hh;
      x = Math.min(width - 8 - hw, Math.max(8 + hw, x));
      y = Math.min(height - 8 - hh, Math.max(8 + hh, y));
      item.el.style.left = `${x}px`;
      item.el.style.top = `${y}px`;
      item.el.classList.toggle("lit", recallName === item.expert.name);
    });
  }

  function setData(data) {
    experts = data.experts || [];
    facts = data.facts || [];
    const counts = new Map();
    facts.forEach((fact) => {
      if (fact.superseded) return;
      counts.set(fact.expert, (counts.get(fact.expert) || 0) + 1);
    });
    const count = Math.max(1, experts.length);
    const cols = count <= 1 ? 1 : Math.min(count, count <= 4 ? 2 : 3);
    const rows = Math.ceil(count / cols);
    nodes = experts.map((expert, index) => {
      const col = index % cols;
      const row = Math.floor(index / cols);
      const rnd = mulberry32((index + 1) * 9973);
      const dust = [];
      const n = 42;
      for (let i = 0; i < n; i += 1) {
        const ang = rnd() * Math.PI * 2;
        const rad = Math.pow(rnd(), 0.55) * (2.4 + (index % 3) * 0.4);
        dust.push({
          x: Math.cos(ang) * rad,
          y: Math.sin(ang) * rad * 0.62,
          s: 7 + rnd() * 16,
          a: 0.08 + rnd() * 0.12,
        });
      }
      return {
        expert,
        name: expert.name,
        x: (col - (cols - 1) / 2) * 12.4,
        y: ((rows - 1) / 2 - row) * 10.6,
        fresh: Boolean(expert.explicit),
        count: counts.get(expert.name) || 0,
        color: COLORS[index % COLORS.length],
        dust,
        spin: index * 0.7,
      };
    });
    const byName = new Map(nodes.map((node) => [node.name, node]));
    stars = [];
    facts.forEach((fact) => {
      const node = byName.get(fact.expert);
      if (!node) return;
      const index = stars.length;
      const ang = index * 2.399963;
      const ring = 0.7 + (index % 7) * 0.22;
      stars.push({
        fact,
        x: node.x + Math.cos(ang) * ring,
        y: node.y + Math.sin(ang) * ring * 0.7,
        dim: Boolean(fact.superseded),
      });
    });
    links = (data.links || []).map((link) => {
      const a = byName.get(String(link.source || "").replace(/^expert:/, "")) || nodes.find((node) => `expert:${node.name}` === link.source);
      const b = byName.get(String(link.target || "").replace(/^expert:/, "")) || nodes.find((node) => `expert:${node.name}` === link.target);
      if (!a || !b) return null;
      return { x1: a.x, y1: a.y, x2: b.x, y2: b.y };
    }).filter(Boolean);
    const layer = ensureLabels();
    labels = [];
    if (layer) {
      layer.replaceChildren();
      nodes.forEach((node) => {
        const el = document.createElement("div");
        el.className = `nebula-label${node.fresh ? " fresh" : ""}`;
        const name = document.createElement("span");
        name.className = "name";
        const meta = document.createElement("span");
        meta.className = "meta";
        const tag = document.createElement("span");
        tag.className = "tag";
        tag.hidden = true;
        el.append(name, meta, tag);
        const item = { el, expert: node.expert, count: node.count, fresh: node.fresh, x: node.x, y: node.y };
        fillLabel(item);
        layer.appendChild(el);
        labels.push(item);
      });
    }
    placeLabels();
  }

  function resize() {
    const width = Math.max(1, canvas.clientWidth || 1);
    const height = Math.max(1, canvas.clientHeight || 1);
    const dpr = Math.min(window.devicePixelRatio || 1, mode === "dim" ? 1 : 1.5);
    const bw = Math.floor(width * dpr);
    const bh = Math.floor(height * dpr);
    if (canvas.width !== bw || canvas.height !== bh) {
      canvas.width = bw;
      canvas.height = bh;
    }
    placeLabels();
  }

  function paint(now) {
    const width = canvas.clientWidth || 1;
    const height = canvas.clientHeight || 1;
    const dpr = canvas.width / width;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const sky = ctx.createLinearGradient(0, 0, width * 0.15, height);
    sky.addColorStop(0, "#12182c");
    sky.addColorStop(1, "#070910");
    ctx.fillStyle = sky;
    ctx.fillRect(0, 0, width, height);
    const t = reduce ? 0 : (now || 0) / 1000;
    ctx.lineWidth = 1;
    links.forEach((link) => {
      const a = project(link.x1, link.y1);
      const b = project(link.x2, link.y2);
      ctx.strokeStyle = "rgba(214, 186, 120, 0.28)";
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
    });
    nodes.forEach((node) => {
      const origin = project(node.x, node.y);
      const boost = recallName && recallName === node.name ? 1.35 : recallName ? 0.55 : 1;
      const [r, g, b] = node.color;
      node.dust.forEach((speck, index) => {
        const ang = t * 0.15 + node.spin + index * 0.02;
        const px = origin.x + (speck.x * Math.cos(ang) - speck.y * Math.sin(ang) * 0.2) * origin.f;
        const py = origin.y - (speck.y * Math.cos(ang) + speck.x * Math.sin(ang) * 0.15) * origin.f;
        const radius = Math.max(2.5, speck.s * origin.f * 0.09);
        const gradient = ctx.createRadialGradient(px, py, 0, px, py, radius);
        const alpha = speck.a * boost;
        gradient.addColorStop(0, `rgba(${r},${g},${b},${Math.min(0.85, alpha * 3.2)})`);
        gradient.addColorStop(0.45, `rgba(${r},${g},${b},${alpha})`);
        gradient.addColorStop(1, `rgba(${r},${g},${b},0)`);
        ctx.fillStyle = gradient;
        ctx.beginPath();
        ctx.arc(px, py, radius, 0, Math.PI * 2);
        ctx.fill();
      });
      const core = ctx.createRadialGradient(origin.x, origin.y, 0, origin.x, origin.y, Math.max(18, 4.2 * origin.f));
      core.addColorStop(0, `rgba(${r},${g},${b},${0.55 * boost})`);
      core.addColorStop(1, `rgba(${r},${g},${b},0)`);
      ctx.fillStyle = core;
      ctx.beginPath();
      ctx.arc(origin.x, origin.y, Math.max(18, 4.2 * origin.f), 0, Math.PI * 2);
      ctx.fill();
    });
    stars.forEach((star) => {
      const p = project(star.x, star.y);
      ctx.fillStyle = star.dim ? "rgba(220, 214, 196, 0.35)" : "rgba(255, 246, 230, 0.92)";
      ctx.beginPath();
      ctx.arc(p.x, p.y, star.dim ? 1.1 : 1.7, 0, Math.PI * 2);
      ctx.fill();
    });
    placeLabels();
  }

  function sample(encode) {
    const bw = canvas.width;
    const bh = canvas.height;
    const tw = Math.min(160, bw);
    const th = Math.min(220, bh);
    if (tw < 8 || th < 8) return null;
    const x = Math.floor((bw - tw) / 2);
    const y = Math.floor((bh - th) / 2);
    const img = ctx.getImageData(x, y, tw, th);
    const lumas = new Float32Array(tw * th);
    let sum = 0;
    let sum2 = 0;
    for (let i = 0; i < tw * th; i += 1) {
      const o = i * 4;
      const luma = (img.data[o] + img.data[o + 1] + img.data[o + 2]) / 3;
      lumas[i] = luma;
      sum += luma;
      sum2 += luma * luma;
    }
    const n = tw * th;
    const mean = sum / n;
    const variance = sum2 / n - mean * mean;
    if (!encode) return { variance, lumas, png: "" };
    const out = document.createElement("canvas");
    out.width = tw;
    out.height = th;
    out.getContext("2d").putImageData(img, 0, 0);
    return { variance, lumas, png: out.toDataURL("image/png") };
  }

  function postFrame(name, shot) {
    if (!window.Android || !Android.onFrame || !shot || !shot.png) return;
    Android.onFrame(name, shot.png, String(shot.variance));
  }

  function captureE2eFrame() {
    if (!e2eShot) return;
    try {
      if (!capturedBefore) {
        if (frameCount < 5) return;
        const shot = sample(true);
        if (!shot || shot.variance <= 6) return;
        capturedBefore = true;
        beforeLumas = shot.lumas;
        canvasVariance = shot.variance;
        postFrame("canvas-before", shot);
        if (window.nebulaHost && window.nebulaHost.probe) window.nebulaHost.probe();
        return;
      }
      if (!beforeLumas || touches <= 0) return;
      const now = performance.now();
      if (!gestureAt) gestureAt = now;
      const elapsed = now - gestureAt;
      if (elapsed < 450 || elapsed > 14000) return;
      const gap = elapsed < 9000 ? 160 : 320;
      if (now - lastSampleAt < gap) return;
      lastSampleAt = now;
      const shot = sample(false);
      if (!shot) return;
      let diff = 0;
      let moved = 0;
      const n = Math.min(beforeLumas.length, shot.lumas.length);
      for (let i = 0; i < n; i += 1) {
        const delta = Math.abs(beforeLumas[i] - shot.lumas[i]);
        diff += delta;
        if (delta > 12) moved += 1;
      }
      const mean = n ? diff / n : 0;
      canvasVariance = Math.max(canvasVariance, shot.variance);
      if (mean <= canvasDiff + 0.05) return;
      canvasDiff = mean;
      canvasMoved = moved;
      const encoded = sample(true);
      if (!encoded || !encoded.png) return;
      postFrame("canvas-after", encoded);
      if (window.nebulaHost && window.nebulaHost.probe) window.nebulaHost.probe();
    } catch (error) {
      console.error("canvas nebula capture", error && error.message ? error.message : error);
    }
  }

  function probeFrame() {
    if (probed || frameCount < 6 || !nodes.length) return;
    const shot = sample(false);
    if (!shot) return;
    const tw = Math.min(96, canvas.width);
    const th = Math.min(72, canvas.height);
    const x = Math.floor((canvas.width - tw) / 2);
    const y = Math.floor((canvas.height - th) / 2);
    const img = ctx.getImageData(x, y, tw, th);
    const lumas = new Float32Array(tw * th);
    for (let i = 0; i < tw * th; i += 1) {
      const o = i * 4;
      lumas[i] = (img.data[o] + img.data[o + 1] + img.data[o + 2]) / 3;
    }
    probe = classifyField(lumas, tw, th);
    probed = true;
    if (probe.lattice) console.info(`canvas2d still lattice rough=${probe.rough.toFixed(2)}`);
  }

  function frame(now) {
    if (!running) return;
    requestAnimationFrame(frame);
    if (mode === "dim" || !canvas.clientWidth || document.hidden) return;
    frameCount += 1;
    resize();
    paint(now);
    probeFrame();
    captureE2eFrame();
  }

  function selectAt(clientX, clientY) {
    const rect = canvas.getBoundingClientRect();
    const x = clientX - rect.left;
    const y = clientY - rect.top;
    const labeled = labels.find((item) => {
      const box = item.el.getBoundingClientRect();
      return clientX >= box.left && clientX <= box.right && clientY >= box.top && clientY <= box.bottom;
    });
    const node = labeled
      ? nodes.find((item) => item.name === labeled.expert.name)
      : nodes.find((item) => {
        const p = project(item.x, item.y);
        return Math.hypot(p.x - x, p.y - y) < Math.max(36, 5 * p.f);
      });
    if (!node) return;
    const fact = facts.find((item) => item.expert === node.name && !item.superseded)
      || facts.find((item) => item.expert === node.name)
      || null;
    if (hooks.onSelect) hooks.onSelect({ kind: "expert", expert: node.expert, expertName: node.name, fact });
  }

  const pointers = new Map();
  let pinch = 0;
  let dragging = false;
  let moved = 0;
  let lastX = 0;
  let lastY = 0;
  canvas.addEventListener("pointerdown", (event) => {
    touches += 1;
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (pointers.size >= 2) {
      const pts = [...pointers.values()];
      pinch = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y) || 1;
      dragging = false;
    } else {
      dragging = true;
      moved = 0;
      lastX = event.clientX;
      lastY = event.clientY;
    }
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!pointers.has(event.pointerId)) return;
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (pointers.size >= 2) {
      const pts = [...pointers.values()];
      const dist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y) || 1;
      if (pinch > 0) camZ = Math.min(80, Math.max(8, camZ * (pinch / dist)));
      pinch = dist;
      dragging = false;
      return;
    }
    if (!dragging) return;
    const dx = event.clientX - lastX;
    const dy = event.clientY - lastY;
    moved += Math.abs(dx) + Math.abs(dy);
    lastX = event.clientX;
    lastY = event.clientY;
    camX -= dx * 0.03;
    camY += dy * 0.03;
  });
  function endPointer(event) {
    const wasPinch = pointers.size >= 2;
    pointers.delete(event.pointerId);
    if (pointers.size < 2) pinch = 0;
    dragging = false;
    if (!wasPinch && moved < 6) selectAt(event.clientX, event.clientY);
  }
  canvas.addEventListener("pointerup", endPointer);
  canvas.addEventListener("pointercancel", (event) => {
    pointers.delete(event.pointerId);
    pinch = 0;
    dragging = false;
  });

  resize();
  requestAnimationFrame(frame);

  return {
    kind: "canvas2d",
    setData,
    resize,
    refreshLabels() {
      labels.forEach((item) => fillLabel(item));
      placeLabels();
    },
    highlight(trace) {
      recallName = trace && trace.mounted && trace.mounted_expert ? trace.mounted_expert : "";
      return { mounted: Boolean(recallName), nodeIds: recallName ? [`expert:${recallName}`] : [] };
    },
    screenPoint(nodeId) {
      const name = String(nodeId || "").replace(/^expert:/, "");
      const node = nodes.find((item) => item.name === name);
      if (!node) return null;
      const p = project(node.x, node.y);
      return { x: p.x, y: p.y };
    },
    focus(name) {
      const node = nodes.find((item) => item.name === name);
      if (!node) return;
      camX = node.x;
      camY = node.y;
      camZ = Math.min(camZ, 18);
    },
    setMode(next) {
      mode = next === "dim" || next === "paused" ? "dim" : "full";
    },
    dispose() {
      running = false;
      if (labelLayer) labelLayer.remove();
      labelLayer = null;
    },
    status() {
      const first = nodes[0];
      const hit = first ? project(first.x, first.y) : { x: 0, y: 0 };
      return {
        renderer: "canvas2d",
        version: "canvas2d",
        path: "canvas2d",
        fallback: "canvas2d",
        zoom: camZ,
        cameraZ: camZ,
        cameraX: camX,
        dpr: window.devicePixelRatio || 1,
        frames: frameCount,
        touches,
        hitX: hit.x,
        hitY: hit.y,
        freshLabels: labels.filter((item) => item.fresh).length,
        kind: "canvas2d",
        canvasVariance,
        canvasDiff,
        canvasMoved,
        flip: probe.flip,
        peak: probe.peak,
        rough: probe.rough,
        lattice: probe.lattice,
        probed,
      };
    },
  };
}

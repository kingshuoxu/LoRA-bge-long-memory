/* WebGL1 星云。Three.js r163 起只创建 webgl2，Mali 的 WebView 经常拿不到。
 * 这条路径自己画粒子云、星和连线，并处理拖动、双指缩放和点选。 */

const VERT = `
  attribute vec3 aPos;
  attribute vec3 aColor;
  attribute float aSize;
  uniform vec2 uRes;
  uniform float uZoom;
  uniform float uYaw;
  uniform float uPitch;
  uniform vec2 uPan;
  varying vec3 vColor;
  void main() {
    float cy = cos(uYaw);
    float sy = sin(uYaw);
    float x1 = aPos.x * cy + aPos.z * sy;
    float z1 = -aPos.x * sy + aPos.z * cy;
    float cx = cos(uPitch);
    float sx = sin(uPitch);
    float y1 = aPos.y * cx - z1 * sx;
    float z2 = aPos.y * sx + z1 * cx;
    float depth = max(0.35, uZoom - z2);
    float f = 1.15;
    float aspect = uRes.x / max(1.0, uRes.y);
    vec2 clip = vec2((x1 / depth) * f + uPan.x, (y1 / depth) * f * aspect + uPan.y);
    gl_Position = vec4(clip, 0.0, 1.0);
    gl_PointSize = clamp(aSize * 70.0 / depth, 2.0, 64.0);
    vColor = aColor;
  }
`;

const FRAG = `
  precision mediump float;
  varying vec3 vColor;
  uniform float uRound;
  void main() {
    if (uRound > 0.5) {
      vec2 p = gl_PointCoord * 2.0 - 1.0;
      float r = length(p);
      if (r > 1.0) discard;
      float glow = exp(-r * r * 3.2);
      gl_FragColor = vec4(vColor * glow, glow);
    } else {
      gl_FragColor = vec4(vColor, 0.85);
    }
  }
`;

function rendererString(gl) {
  const ext = gl.getExtension("WEBGL_debug_renderer_info");
  if (ext) {
    const name = gl.getParameter(ext.UNMASKED_RENDERER_WEBGL);
    if (name) return String(name);
  }
  return String(gl.getParameter(gl.RENDERER) || "");
}

function compile(gl, type, source) {
  const shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    const log = gl.getShaderInfoLog(shader);
    gl.deleteShader(shader);
    throw new Error(log || "shader");
  }
  return shader;
}

export function gl2Available() {
  const canvas = document.createElement("canvas");
  canvas.width = 8;
  canvas.height = 8;
  let gl = null;
  try {
    gl = canvas.getContext("webgl2", { failIfMajorPerformanceCaveat: false });
    if (!gl) return { ok: false, renderer: "", reason: "no webgl2" };
    const vs = compile(gl, gl.VERTEX_SHADER, `#version 300 es
      void main() { gl_Position = vec4(0.0, 0.0, 0.0, 1.0); gl_PointSize = 1.0; }
    `);
    const fs = compile(gl, gl.FRAGMENT_SHADER, `#version 300 es
      precision mediump float;
      out vec4 outColor;
      void main() { outColor = vec4(1.0, 1.0, 1.0, 1.0); }
    `);
    const program = gl.createProgram();
    gl.attachShader(program, vs);
    gl.attachShader(program, fs);
    gl.linkProgram(program);
    const ok = gl.getProgramParameter(program, gl.LINK_STATUS);
    const renderer = rendererString(gl);
    return { ok: Boolean(ok), renderer, reason: ok ? "" : "webgl2 shader" };
  } catch (error) {
    return { ok: false, renderer: gl ? rendererString(gl) : "", reason: String(error && error.message ? error.message : error) };
  } finally {
    if (gl) {
      const lose = gl.getExtension("WEBGL_lose_context");
      if (lose) lose.loseContext();
    }
  }
}

function mulberry(seed) {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6D2B79F5) >>> 0;
    let value = state;
    value = Math.imul(value ^ (value >>> 15), value | 1);
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
}

const PALETTE = [
  [1.0, 0.45, 0.28],
  [0.25, 0.9, 0.82],
  [1.0, 0.78, 0.32],
  [0.62, 0.4, 1.0],
  [1.0, 0.5, 0.55],
  [0.45, 0.7, 1.0],
];

export function createGl1Nebula(canvas, hooks) {
  const gl = canvas.getContext("webgl", {
    alpha: false,
    antialias: false,
    depth: false,
    stencil: false,
    failIfMajorPerformanceCaveat: false,
  });
  if (!gl) return null;
  let program;
  try {
    const vs = compile(gl, gl.VERTEX_SHADER, VERT);
    const fs = compile(gl, gl.FRAGMENT_SHADER, FRAG);
    program = gl.createProgram();
    gl.attachShader(program, vs);
    gl.attachShader(program, fs);
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      throw new Error(gl.getProgramInfoLog(program) || "link");
    }
  } catch (error) {
    console.error("nebula webgl1", error && error.message ? error.message : error);
    const lose = gl.getExtension("WEBGL_lose_context");
    if (lose) lose.loseContext();
    return null;
  }

  const buffer = gl.createBuffer();
  const aPos = gl.getAttribLocation(program, "aPos");
  const aColor = gl.getAttribLocation(program, "aColor");
  const aSize = gl.getAttribLocation(program, "aSize");
  const uRes = gl.getUniformLocation(program, "uRes");
  const uZoom = gl.getUniformLocation(program, "uZoom");
  const uYaw = gl.getUniformLocation(program, "uYaw");
  const uPitch = gl.getUniformLocation(program, "uPitch");
  const uPan = gl.getUniformLocation(program, "uPan");
  const uRound = gl.getUniformLocation(program, "uRound");
  gl.useProgram(program);
  gl.enable(gl.BLEND);
  gl.blendFunc(gl.SRC_ALPHA, gl.ONE);
  gl.clearColor(0.027, 0.035, 0.063, 1);

  const name = rendererString(gl);
  let experts = [];
  let facts = [];
  let links = [];
  let points = [];
  let stars = [];
  let lines = [];
  let yaw = 0.2;
  let pitch = 0.15;
  let zoom = 8.5;
  let panX = 0;
  let panY = 0;
  let userMoved = false;
  let frames = 0;
  let running = true;
  let mode = "full";
  let hitX = 0;
  let hitY = 0;
  let labelLayer = null;
  const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function layout() {
    points = [];
    stars = [];
    lines = [];
    const count = Math.max(1, experts.length);
    experts.forEach((expert, index) => {
      const ang = (index / count) * Math.PI * 2 - Math.PI / 2;
      const ring = count === 1 ? 0 : 3.2;
      const ox = Math.cos(ang) * ring;
      const oy = Math.sin(ang) * ring * 0.62;
      expert.x = ox;
      expert.y = oy;
      const rnd = mulberry((index + 1) * 997);
      const rgb = PALETTE[index % PALETTE.length];
      const fresh = Boolean(expert.explicit);
      for (let i = 0; i < 80; i += 1) {
        const r = Math.pow(rnd(), 0.55) * 1.7;
        const a = rnd() * Math.PI * 2;
        points.push({
          x: ox + Math.cos(a) * r,
          y: oy + Math.sin(a) * r * 0.72,
          z: (rnd() - 0.5) * 0.8,
          r: rgb[0], g: rgb[1], b: rgb[2],
          size: 0.35 + rnd() * 0.55,
          spin: rnd() * 6,
        });
      }
      for (let i = 0; i < 16; i += 1) {
        const r = 0.2 + rnd() * 2.4;
        const a = rnd() * Math.PI * 2;
        stars.push({
          x: ox + Math.cos(a) * r,
          y: oy + Math.sin(a) * r * 0.7,
          z: (rnd() - 0.5) * 0.4,
          r: fresh ? 1 : 0.95,
          g: fresh ? 0.9 : 0.92,
          b: fresh ? 0.55 : 0.82,
          size: 0.16 + rnd() * 0.18,
          spin: rnd() * 8,
        });
      }
    });
    const indexOf = new Map(experts.map((expert, index) => [expert.name, index]));
    links.forEach((link) => {
      if (link.kind !== "entity" && link.kind !== "semantic") return;
      const factA = facts.find((fact) => fact.id === link.source);
      const factB = facts.find((fact) => fact.id === link.target);
      if (!factA || !factB) return;
      const ia = indexOf.get(factA.expert);
      const ib = indexOf.get(factB.expert);
      if (ia == null || ib == null || ia === ib) return;
      lines.push([ia, ib]);
    });
  }

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

  function placeLabels() {
    const layer = ensureLabels();
    if (!layer) return;
    layer.replaceChildren();
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "nebula-leaders");
    layer.appendChild(svg);
    const width = canvas.clientWidth || 1;
    const height = canvas.clientHeight || 1;
    experts.forEach((expert, index) => {
      const at = project(expert.x, expert.y, 0);
      if (!at) return;
      if (index === 0) {
        hitX = at.x;
        hitY = at.y;
      }
      const el = document.createElement("div");
      const count = facts.filter((fact) => fact.expert === expert.name && !fact.superseded).length;
      const fresh = Boolean(expert.explicit);
      el.className = `nebula-label${fresh ? " fresh" : ""}`;
      const nameEl = document.createElement("span");
      nameEl.className = "name";
      let title = expert.display_name || expert.name || "";
      if (window.i18n && window.i18n.getLocale && window.i18n.getLocale() === "en" && window.i18n.foreignName) {
        title = window.i18n.foreignName(title);
      }
      nameEl.textContent = title;
      const meta = document.createElement("span");
      meta.className = "meta";
      const countText = window.i18n && window.i18n.t ? window.i18n.t("nebula.count", { n: count }) : `${count} 条事实`;
      meta.textContent = ` · ${countText}`;
      el.append(nameEl, meta);
      if (fresh) {
        const tag = document.createElement("span");
        tag.className = "tag";
        const word = window.i18n && window.i18n.t ? window.i18n.t("nebula.new") : "新";
        tag.textContent = ` · ${word}`;
        el.append(tag);
      }
      const lx = Math.min(width - 80, Math.max(80, at.x + 36));
      const ly = Math.min(height - 24, Math.max(24, at.y - 28));
      el.style.left = `${lx}px`;
      el.style.top = `${ly}px`;
      layer.appendChild(el);
      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("x1", String(at.x));
      line.setAttribute("y1", String(at.y));
      line.setAttribute("x2", String(lx));
      line.setAttribute("y2", String(ly));
      svg.appendChild(line);
    });
  }

  function project(x, y, z) {
    const cy = Math.cos(yaw);
    const sy = Math.sin(yaw);
    const x1 = x * cy + z * sy;
    const z1 = -x * sy + z * cy;
    const cx = Math.cos(pitch);
    const sx = Math.sin(pitch);
    const y1 = y * cx - z1 * sx;
    const z2 = y * sx + z1 * cx;
    const depth = zoom - z2;
    if (depth < 0.35) return null;
    const f = 1.15;
    const width = canvas.clientWidth || 1;
    const height = canvas.clientHeight || 1;
    const aspect = width / height;
    const clipX = (x1 / depth) * f + panX;
    const clipY = (y1 / depth) * f * aspect + panY;
    return {
      x: (clipX * 0.5 + 0.5) * width,
      y: (-clipY * 0.5 + 0.5) * height,
    };
  }

  function pushVertex(out, item) {
    out.push(item.x, item.y, item.z, item.r, item.g, item.b, item.size);
  }

  function draw(list, round) {
    if (!list.length) return;
    const data = [];
    list.forEach((item) => pushVertex(data, item));
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(data), gl.DYNAMIC_DRAW);
    const stride = 7 * 4;
    gl.enableVertexAttribArray(aPos);
    gl.vertexAttribPointer(aPos, 3, gl.FLOAT, false, stride, 0);
    gl.enableVertexAttribArray(aColor);
    gl.vertexAttribPointer(aColor, 3, gl.FLOAT, false, stride, 12);
    gl.enableVertexAttribArray(aSize);
    gl.vertexAttribPointer(aSize, 1, gl.FLOAT, false, stride, 24);
    gl.uniform1f(uRound, round);
    gl.drawArrays(round ? gl.POINTS : gl.LINES, 0, list.length);
  }

  function resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const width = Math.max(1, Math.floor((canvas.clientWidth || 1) * dpr));
    const height = Math.max(1, Math.floor((canvas.clientHeight || 1) * dpr));
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
    gl.viewport(0, 0, canvas.width, canvas.height);
  }

  function frame(now) {
    if (!running) return;
    if (mode !== "dim") requestAnimationFrame(frame);
    frames += 1;
    const t = reduce ? 0 : (now || 0) / 1000;
    if (!userMoved && !reduce && mode !== "dim") yaw = 0.2 + t * 0.12;
    points.forEach((point) => {
      point.z = Math.sin(t * 0.8 + point.spin) * 0.35;
    });
    resize();
    gl.useProgram(program);
    gl.uniform2f(uRes, canvas.clientWidth || 1, canvas.clientHeight || 1);
    gl.uniform1f(uZoom, zoom);
    gl.uniform1f(uYaw, yaw);
    gl.uniform1f(uPitch, pitch);
    gl.uniform2f(uPan, panX, panY);
    gl.clear(gl.COLOR_BUFFER_BIT);
    const lineVerts = [];
    lines.forEach(([ia, ib]) => {
      const a = experts[ia];
      const b = experts[ib];
      if (!a || !b) return;
      lineVerts.push(
        { x: a.x, y: a.y, z: 0, r: 0.85, g: 0.78, b: 0.55, size: 1 },
        { x: b.x, y: b.y, z: 0, r: 0.85, g: 0.78, b: 0.55, size: 1 },
      );
    });
    draw(lineVerts, 0);
    draw(points, 1);
    draw(stars, 1);
    placeLabels();
    if (mode === "dim") running = false;
  }

  function hitExpert(clientX, clientY) {
    const rect = canvas.getBoundingClientRect();
    const x = clientX - rect.left;
    const y = clientY - rect.top;
    let best = null;
    let bestDist = 72;
    experts.forEach((expert) => {
      const at = project(expert.x, expert.y, 0);
      if (!at) return;
      const dist = Math.hypot(at.x - x, at.y - y);
      if (dist < bestDist) {
        best = expert;
        bestDist = dist;
      }
    });
    const layer = labelLayer;
    if (!best && layer) {
      const nodes = layer.querySelectorAll(".nebula-label");
      nodes.forEach((el, index) => {
        const box = el.getBoundingClientRect();
        if (clientX >= box.left && clientX <= box.right && clientY >= box.top && clientY <= box.bottom) {
          best = experts[index] || best;
        }
      });
    }
    return best;
  }

  function selectExpert(expert) {
    if (!expert || !hooks.onSelect) return;
    const fact = facts.find((item) => item.expert === expert.name && !item.superseded)
      || facts.find((item) => item.expert === expert.name)
      || null;
    hooks.onSelect({ kind: "expert", expert, expertName: expert.name, fact });
  }

  const pointers = new Map();
  let touches = 0;
  let pinch = 0;
  let moved = 0;
  canvas.addEventListener("pointerdown", (event) => {
    touches += 1;
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (pointers.size >= 2) {
      const pts = [...pointers.values()];
      pinch = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y) || 1;
    } else {
      moved = 0;
    }
    try { canvas.setPointerCapture(event.pointerId); } catch (error) {}
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!pointers.has(event.pointerId)) return;
    const prev = pointers.get(event.pointerId);
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (pointers.size >= 2) {
      const pts = [...pointers.values()];
      const dist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y) || 1;
      if (pinch > 0) {
        const factor = pinch / dist;
        zoom = Math.min(28, Math.max(3.2, zoom * factor));
        userMoved = true;
      }
      pinch = dist;
      return;
    }
    const dx = event.clientX - prev.x;
    const dy = event.clientY - prev.y;
    moved += Math.abs(dx) + Math.abs(dy);
    if (moved > 3) {
      userMoved = true;
      yaw -= dx * 0.005;
      pitch = Math.min(1.1, Math.max(-1.1, pitch + dy * 0.005));
    }
  });
  function endPointer(event) {
    const wasPinch = pointers.size >= 2;
    pointers.delete(event.pointerId);
    if (pointers.size < 2) pinch = 0;
    if (wasPinch || moved > 5) return;
    selectExpert(hitExpert(event.clientX, event.clientY));
  }
  canvas.addEventListener("pointerup", endPointer);
  canvas.addEventListener("pointercancel", (event) => {
    pointers.delete(event.pointerId);
    pinch = 0;
  });

  resize();
  requestAnimationFrame(frame);
  console.info("nebula webgl1", name);

  return {
    kind: "gl1",
    setData(data) {
      experts = (data && data.experts) || [];
      facts = (data && data.facts) || [];
      links = (data && data.links) || [];
      layout();
      placeLabels();
    },
    resize,
    refreshLabels() { placeLabels(); },
    highlight() { return { mounted: false, nodeIds: [] }; },
    screenPoint() { return null; },
    focus() {},
    setMode(next) {
      const paused = next === "dim" || next === "paused";
      mode = paused ? "dim" : "full";
      if (!paused && !running) {
        running = true;
        requestAnimationFrame(frame);
      }
    },
    dispose() {
      running = false;
      if (labelLayer) labelLayer.remove();
      const lose = gl.getExtension("WEBGL_lose_context");
      if (lose) lose.loseContext();
    },
    status() {
      return {
        renderer: name,
        version: "webgl1",
        zoom,
        cameraZ: zoom,
        cameraX: yaw,
        dpr: window.devicePixelRatio || 1,
        path: "webgl1",
        fallback: "webgl1",
        frames,
        touches,
        hitX,
        hitY,
        freshLabels: experts.filter((expert) => expert.explicit).length,
        kind: "gl1",
      };
    },
  };
}

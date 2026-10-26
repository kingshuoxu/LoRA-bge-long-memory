import { classifyField } from "../nebula/nebula-pixels.js";

/* 全屏深空背景。训练时停掉动画。
 * 片段着色器用 highp，散列不用 sin*大常数。中精度下那条散列和 gl_FragCoord 会在
 * 半精度 GPU 上变成整屏棕色渐变加菱形白点。画完读一块像素，仍像格子就改画 canvas。
 */

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

function postSky(canvas, variance) {
  if (!e2ePage() || !window.Android || !Android.onFrame) return;
  try {
    const tw = Math.min(200, canvas.width || 1);
    const th = Math.min(280, canvas.height || 1);
    const shot = document.createElement("canvas");
    shot.width = tw;
    shot.height = th;
    const ctx = shot.getContext("2d");
    if (!ctx) return;
    ctx.drawImage(canvas, 0, 0, tw, th);
    Android.onFrame("canvas-sky", shot.toDataURL("image/png"), String(variance));
  } catch (error) {
    console.info(`sky frame ${error && error.message ? error.message : error}`);
  }
}

function readLumas(gl, x, y, tw, th) {
  const pixels = new Uint8Array(tw * th * 4);
  gl.readPixels(x, y, tw, th, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
  const lumas = new Float32Array(tw * th);
  for (let i = 0; i < tw * th; i += 1) {
    const o = i * 4;
    lumas[i] = (pixels[o] + pixels[o + 1] + pixels[o + 2]) / 3;
  }
  return lumas;
}

export function startSky() {
  const canvas = document.getElementById("sky");
  if (!canvas || canvas.dataset.skyReady === "1") return;
  canvas.dataset.skyReady = "1";
  const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const gl = canvas.getContext("webgl", {
    alpha: false,
    antialias: false,
    depth: false,
    stencil: false,
    powerPreference: "low-power",
    preserveDrawingBuffer: e2ePage(),
  });
  if (!gl) {
    mountSoftwareSky(canvas, "no webgl");
    return;
  }

  const vert = `
    attribute vec2 aPos;
    void main() { gl_Position = vec4(aPos, 0.0, 1.0); }
  `;
  const frag = `
    precision highp float;
    uniform vec2 uRes;
    uniform float uTime;
    uniform float uDim;

    float hash(vec2 p) {
      vec3 p3 = fract(vec3(p.xyx) * 0.1031);
      p3 += dot(p3, p3.yzx + 33.33);
      return fract((p3.x + p3.y) * p3.z);
    }
    float noise(vec2 p) {
      vec2 i = floor(p);
      vec2 f = fract(p);
      float a = hash(i);
      float b = hash(i + vec2(1.0, 0.0));
      float c = hash(i + vec2(0.0, 1.0));
      float d = hash(i + vec2(1.0, 1.0));
      vec2 u = f * f * (3.0 - 2.0 * f);
      return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
    }
    float fbm(vec2 p) {
      float v = 0.0;
      float a = 0.5;
      for (int i = 0; i < 4; i++) {
        v += a * noise(p);
        p = p * 2.02 + vec2(1.7, 9.2);
        a *= 0.5;
      }
      return v;
    }
    float stars(vec2 uv, float scale, float density, float drift) {
      vec2 p = uv * scale + vec2(drift, drift * 0.37);
      vec2 id = floor(p);
      vec2 f = fract(p) - 0.5;
      float h = hash(id);
      if (h > density) return 0.0;
      float tw = uDim > 0.5 ? 0.85 : (0.62 + 0.38 * sin(uTime * (1.2 + h * 3.5) + h * 6.28318));
      float d = length(f);
      float size = mix(90.0, 220.0, h);
      return exp(-d * d * size) * tw * (0.35 + h);
    }

    void main() {
      vec2 uv = (gl_FragCoord.xy - 0.5 * uRes) / max(uRes.y, 1.0);
      float t = uTime * (uDim > 0.5 ? 0.18 : 1.0);
      vec2 scroll = uv + vec2(t * 0.004, t * 0.0015);
      float ang = -0.42;
      float ca = cos(ang);
      float sa = sin(ang);
      vec2 bandUv = vec2(ca * uv.x - sa * uv.y, sa * uv.x + ca * uv.y);
      float lanes = fbm(bandUv * 2.2 + vec2(t * 0.01, 0.4));
      float band = exp(-bandUv.y * bandUv.y / 0.16);
      float core = exp(-bandUv.y * bandUv.y / 0.02);
      float gasA = fbm(scroll * 1.15);
      float gasB = fbm(scroll * 1.9 + vec2(4.0, -2.0));
      vec3 indigo = vec3(0.012, 0.016, 0.04);
      vec3 violet = vec3(0.22, 0.08, 0.32);
      vec3 teal = vec3(0.04, 0.22, 0.24);
      vec3 gold = vec3(0.55, 0.38, 0.14);
      vec3 col = indigo;
      col += violet * gasA * 0.42;
      col += teal * gasB * 0.28;
      col += gold * band * (0.55 + lanes * 0.35);
      col += vec3(0.92, 0.9, 0.82) * core * (0.28 + lanes * 0.16);
      col += violet * band * 0.12;
      float dust = smoothstep(0.46, 0.72, fbm(bandUv * 3.4 + vec2(1.7, 0.2)));
      float dust2 = smoothstep(0.55, 0.82, fbm(bandUv * 6.2 - vec2(0.4, 1.4)));
      float lane = smoothstep(0.08, 0.0, abs(bandUv.y + 0.045 * sin(bandUv.x * 3.0)));
      col *= 1.0 - dust * band * 0.55;
      col *= 1.0 - dust2 * band * 0.4;
      col *= 1.0 - lane * band * 0.45;
      float s1 = stars(uv + vec2(t * 0.002, 0.0), 42.0, 0.18, t * 0.01);
      float s2 = stars(uv + vec2(-t * 0.004, t * 0.001), 90.0, 0.12, 2.0);
      float s3 = stars(uv, 160.0, 0.08, 5.0);
      vec3 starCol = mix(vec3(0.75, 0.84, 1.0), vec3(1.0, 0.86, 0.62), step(0.72, hash(floor(uv * 40.0))));
      col += starCol * (s1 * 0.9 + s2 * 0.7 + s3 * 0.45);
      float vig = smoothstep(1.55, 0.2, length(uv));
      col *= vig;
      float grain = (hash(gl_FragCoord.xy * 0.35) - 0.5) * 0.012;
      col += grain;
      if (uDim > 0.5) col = mix(col, indigo, 0.28);
      gl_FragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
    }
  `;

  function compile(type, source) {
    const shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      console.info(`sky shader ${gl.getShaderInfoLog(shader) || ""}`);
      gl.deleteShader(shader);
      return null;
    }
    return shader;
  }
  const vs = compile(gl.VERTEX_SHADER, vert);
  const fs = compile(gl.FRAGMENT_SHADER, frag);
  if (!vs || !fs) {
    mountSoftwareSky(canvas, "sky shader");
    return;
  }
  const program = gl.createProgram();
  gl.attachShader(program, vs);
  gl.attachShader(program, fs);
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    mountSoftwareSky(canvas, "sky link");
    return;
  }
  const buffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(program, "aPos");
  const uRes = gl.getUniformLocation(program, "uRes");
  const uTime = gl.getUniformLocation(program, "uTime");
  const uDim = gl.getUniformLocation(program, "uDim");
  gl.useProgram(program);
  gl.enableVertexAttribArray(loc);
  gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);

  let mode = "full";
  let running = true;
  let last = 0;
  let probed = false;
  let skyTries = 0;
  const start = performance.now();
  const debug = gl.getExtension("WEBGL_debug_renderer_info");
  const rendererName = debug ? String(gl.getParameter(debug.UNMASKED_RENDERER_WEBGL) || "") : "";
  const software = /swiftshader|llvmpipe|softpipe/i.test(rendererName);
  const staticSky = reduce || software;

  function resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, mode === "dim" ? 1 : 1.25);
    const width = Math.max(1, Math.floor(canvas.clientWidth * dpr));
    const height = Math.max(1, Math.floor(canvas.clientHeight * dpr));
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
    gl.viewport(0, 0, canvas.width, canvas.height);
  }

  function probe() {
    if (probed) return false;
    const bw = gl.drawingBufferWidth || canvas.width;
    const bh = gl.drawingBufferHeight || canvas.height;
    const tw = 96;
    const th = 72;
    if (bw < tw + 4 || bh < th + 4) return false;
    probed = true;
    const spots = [
      [Math.floor((bw - tw) / 2), Math.floor((bh - th) / 2)],
      [2, 2],
      [Math.max(2, bw - tw - 2), Math.max(2, bh - th - 2)],
    ];
    let worst = null;
    for (let i = 0; i < spots.length; i += 1) {
      const lumas = readLumas(gl, spots[i][0], spots[i][1], tw, th);
      const report = classifyField(lumas, tw, th);
      if (!worst || report.rough > worst.rough) worst = report;
      if (report.lattice) {
        console.info(`sky lattice flip=${report.flip.toFixed(3)} rough=${report.rough.toFixed(2)} peak=${report.peak.toFixed(3)}`);
        running = false;
        mountSoftwareSky(canvas, "lattice");
        return true;
      }
    }
    if (worst && e2ePage()) {
      const sw = Math.min(200, bw);
      const sh = Math.min(280, bh);
      const sx = Math.floor((bw - sw) / 2);
      const sy = Math.floor((bh - sh) / 2);
      const pixels = new Uint8Array(sw * sh * 4);
      gl.readPixels(sx, sy, sw, sh, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
      const view = document.createElement("canvas");
      view.width = sw;
      view.height = sh;
      const ctx = view.getContext("2d");
      const img = ctx.createImageData(sw, sh);
      for (let row = 0; row < sh; row += 1) {
        const src = (sh - 1 - row) * sw * 4;
        img.data.set(pixels.subarray(src, src + sw * 4), row * sw * 4);
      }
      ctx.putImageData(img, 0, 0);
      if (window.Android && Android.onFrame) Android.onFrame("canvas-sky", view.toDataURL("image/png"), String(worst.variance));
    }
    return false;
  }

  function draw(now) {
    resize();
    gl.uniform2f(uRes, canvas.width, canvas.height);
    const frozen = staticSky || mode === "dim";
    gl.uniform1f(uTime, frozen ? 2.4 : (now - start) / 1000);
    gl.uniform1f(uDim, frozen ? 1 : 0);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    try {
      if (probe()) return;
    } catch (error) {
      console.info(`sky probe ${error && error.message ? error.message : error}`);
      running = false;
      mountSoftwareSky(canvas, "probe");
    }
  }

  function frame(now) {
    if (!running) return;
    if (staticSky || mode === "dim") {
      draw(now);
      skyTries += 1;
      if (!probed && skyTries < 40) {
        requestAnimationFrame(frame);
        return;
      }
      running = false;
      return;
    }
    requestAnimationFrame(frame);
    if (document.hidden) return;
    if (now - last < 16) return;
    last = now;
    draw(now);
  }

  function resume() {
    if (staticSky || mode === "dim") {
      draw(performance.now());
      running = false;
      return;
    }
    if (!running) {
      running = true;
      requestAnimationFrame(frame);
    }
  }

  window.addEventListener("resize", () => {
    if (running || staticSky) draw(performance.now());
  });
  window.sky = {
    renderer: rendererName || String(gl.getParameter(gl.RENDERER) || ""),
    version: "webgl",
    setMode(next) {
      mode = next === "dim" ? "dim" : "full";
      resume();
    },
  };
  requestAnimationFrame(frame);
}

function mountSoftwareSky(target, reason) {
  const next = document.createElement("canvas");
  next.id = "sky";
  next.dataset.skyReady = "1";
  target.replaceWith(next);
  const ctx = next.getContext("2d");
  if (!ctx) {
    window.sky = { setMode() {}, renderer: "", version: "none", error: reason || "" };
    return;
  }
  const rnd = mulberry32(0x51e0);
  const stars = [];
  for (let i = 0; i < 140; i += 1) {
    stars.push({
      x: rnd(),
      y: rnd(),
      r: 0.6 + rnd() * 1.8,
      halo: 2.2 + rnd() * 3.4,
      p: rnd() * 6.2,
      cool: rnd() > 0.72,
    });
  }
  const clouds = [
    { x: 0.32, y: 0.42, rx: 0.55, ry: 0.18, color: "120, 86, 42", alpha: 0.42 },
    { x: 0.58, y: 0.48, rx: 0.42, ry: 0.16, color: "92, 48, 130", alpha: 0.34 },
    { x: 0.46, y: 0.4, rx: 0.28, ry: 0.1, color: "40, 90, 110", alpha: 0.28 },
  ];
  let live = true;
  let posted = false;
  function paint(now) {
    if (!live) return;
    if (live) requestAnimationFrame(paint);
    const w = Math.max(1, next.clientWidth || 1);
    const h = Math.max(1, next.clientHeight || 1);
    const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    const bw = Math.max(1, Math.floor(w * dpr));
    const bh = Math.max(1, Math.floor(h * dpr));
    if (next.width !== bw || next.height !== bh) {
      next.width = bw;
      next.height = bh;
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const g = ctx.createLinearGradient(0, 0, w * 0.2, h);
    g.addColorStop(0, "#141c33");
    g.addColorStop(0.55, "#0c1224");
    g.addColorStop(1, "#070910");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, w, h);
    clouds.forEach((cloud) => {
      const gradient = ctx.createRadialGradient(cloud.x * w, cloud.y * h, 0, cloud.x * w, cloud.y * h, Math.max(w, h) * cloud.rx);
      gradient.addColorStop(0, `rgba(${cloud.color},${cloud.alpha})`);
      gradient.addColorStop(0.45, `rgba(${cloud.color},${cloud.alpha * 0.35})`);
      gradient.addColorStop(1, `rgba(${cloud.color},0)`);
      ctx.fillStyle = gradient;
      ctx.fillRect(0, 0, w, h);
    });
    const t = (now || 0) / 1000;
    stars.forEach((star) => {
      const tw = 0.55 + 0.45 * Math.sin(t * 1.3 + star.p);
      const x = star.x * w;
      const y = star.y * h;
      ctx.fillStyle = star.cool ? `rgba(186, 206, 255, ${0.18 * tw})` : `rgba(255, 236, 206, ${0.16 * tw})`;
      ctx.beginPath();
      ctx.arc(x, y, star.halo, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = `rgba(255, 248, 236, ${0.85 * tw})`;
      ctx.beginPath();
      ctx.arc(x, y, star.r, 0, Math.PI * 2);
      ctx.fill();
    });
    if (!posted) {
      posted = true;
      postSky(next, 40);
    }
  }
  requestAnimationFrame(paint);
  window.sky = {
    renderer: "canvas2d",
    version: "2d",
    error: reason || "",
    setMode(nextMode) {
      live = nextMode !== "dim";
      if (live) requestAnimationFrame(paint);
    },
  };
  console.info(`sky canvas2d ${reason || ""}`);
}

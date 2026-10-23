/* 全屏深空背景。训练时停掉动画；SwiftShader 只画一帧静态银河。 */
(function () {
  const canvas = document.getElementById("sky");
  if (!canvas) return;
  const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const gl = canvas.getContext("webgl", {
    alpha: false,
    antialias: false,
    depth: false,
    stencil: false,
    powerPreference: "low-power",
    preserveDrawingBuffer: false,
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
    precision mediump float;
    uniform vec2 uRes;
    uniform float uTime;
    uniform float uDim;

    float hash(vec2 p) {
      return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
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
      float tw = uDim > 0.5 ? 0.85 : (0.62 + 0.38 * sin(uTime * (1.2 + h * 3.5) + h * 40.0));
      float d = length(f);
      float size = mix(90.0, 280.0, h);
      return exp(-d * d * size) * tw * (0.35 + h);
    }

    void main() {
      vec2 uv = (gl_FragCoord.xy - 0.5 * uRes) / uRes.y;
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
      col += gold * band * (0.62 + lanes * 0.48);
      col += vec3(0.92, 0.9, 0.82) * core * (0.34 + lanes * 0.22);
      col += violet * band * 0.16;
      float dust = smoothstep(0.46, 0.72, fbm(bandUv * 3.4 + vec2(1.7, 0.2)));
      float dust2 = smoothstep(0.55, 0.82, fbm(bandUv * 6.2 - vec2(0.4, 1.4)));
      float lane = smoothstep(0.08, 0.0, abs(bandUv.y + 0.045 * sin(bandUv.x * 3.0)));
      col *= 1.0 - dust * band * 0.72;
      col *= 1.0 - dust2 * band * 0.55;
      col *= 1.0 - lane * band * 0.62;
      float s1 = stars(uv + vec2(t * 0.002, 0.0), 42.0, 0.22, t * 0.01);
      float s2 = stars(uv + vec2(-t * 0.004, t * 0.001), 90.0, 0.16, 2.0);
      float s3 = stars(uv, 170.0, 0.10, 5.0);
      vec3 starCol = mix(vec3(0.75, 0.84, 1.0), vec3(1.0, 0.86, 0.62), step(0.72, hash(floor(uv * 40.0))));
      col += starCol * (s1 * 1.15 + s2 * 0.85 + s3 * 0.55);
      float vig = smoothstep(1.55, 0.2, length(uv));
      col *= vig;
      float grain = (hash(gl_FragCoord.xy + fract(uTime * 17.0)) - 0.5) * (uDim > 0.5 ? 0.02 : 0.045);
      col += grain;
      if (uDim > 0.5) col = mix(col, indigo, 0.28);
      gl_FragColor = vec4(col, 1.0);
    }
  `;

  function compile(type, source) {
    const shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
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

  function draw(now) {
    resize();
    gl.uniform2f(uRes, canvas.width, canvas.height);
    const frozen = staticSky || mode === "dim";
    gl.uniform1f(uTime, frozen ? 2.4 : (now - start) / 1000);
    gl.uniform1f(uDim, frozen ? 1 : 0);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }

  function frame(now) {
    if (!running) return;
    if (staticSky || mode === "dim") {
      draw(now);
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

  window.addEventListener("resize", () => draw(performance.now()));
  window.sky = {
    renderer: rendererName || String(gl.getParameter(gl.RENDERER) || ""),
    version: "webgl",
    setMode(next) {
      mode = next === "dim" ? "dim" : "full";
      resume();
    },
  };
  requestAnimationFrame(frame);

  function mountSoftwareSky(target, reason) {
    const next = document.createElement("canvas");
    next.id = "sky";
    target.replaceWith(next);
    const ctx = next.getContext("2d");
    if (!ctx) {
      window.sky = { setMode() {}, renderer: "", version: "none", error: reason || "" };
      return;
    }
    let live = true;
    const stars = [];
    for (let i = 0; i < 80; i += 1) {
      stars.push({ x: Math.random(), y: Math.random(), r: 0.6 + Math.random() * 1.6, p: Math.random() * 6 });
    }
    function paint(now) {
      if (!live) return;
      requestAnimationFrame(paint);
      const w = next.clientWidth || 1;
      const h = next.clientHeight || 1;
      if (next.width !== w || next.height !== h) {
        next.width = w;
        next.height = h;
      }
      const g = ctx.createLinearGradient(0, 0, 0, h);
      g.addColorStop(0, "#10182a");
      g.addColorStop(1, "#070910");
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, w, h);
      const t = (now || 0) / 1000;
      stars.forEach((star) => {
        const tw = 0.45 + 0.55 * Math.sin(t * 1.4 + star.p);
        ctx.fillStyle = `rgba(238, 232, 214, ${tw})`;
        ctx.beginPath();
        ctx.arc(star.x * w, star.y * h, star.r, 0, Math.PI * 2);
        ctx.fill();
      });
    }
    requestAnimationFrame(paint);
    window.sky = {
      renderer: "canvas2d",
      version: "2d",
      error: reason || "",
      setMode(nextMode) { live = nextMode !== "dim"; if (live) requestAnimationFrame(paint); },
    };
  }
})();

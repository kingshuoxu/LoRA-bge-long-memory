import * as THREE from "./vendor/three.module.js";

const PALETTES = [
  { core: [1.15, 0.28, 0.16], mid: [0.72, 0.14, 0.12], edge: [0.38, 0.07, 0.09], wisp: [0.98, 0.62, 0.18] },
  { core: [0.14, 0.95, 0.82], mid: [0.06, 0.50, 0.52], edge: [0.04, 0.20, 0.30], wisp: [0.45, 0.72, 1.05] },
  { core: [1.08, 0.74, 0.18], mid: [0.64, 0.34, 0.08], edge: [0.30, 0.12, 0.04], wisp: [0.95, 0.32, 0.16] },
  { core: [0.58, 0.24, 1.08], mid: [0.30, 0.10, 0.64], edge: [0.12, 0.05, 0.30], wisp: [0.78, 0.38, 0.92] },
  { core: [1.08, 0.34, 0.44], mid: [0.60, 0.14, 0.24], edge: [0.28, 0.06, 0.12], wisp: [1.00, 0.58, 0.42] },
  { core: [0.24, 0.46, 1.08], mid: [0.10, 0.20, 0.64], edge: [0.05, 0.08, 0.28], wisp: [0.40, 0.78, 0.98] },
];

const GAS_VERT = `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

const POINT_VERT = `
  attribute float aSize;
  attribute float aAlpha;
  attribute vec3 aColor;
  varying vec3 vColor;
  varying float vAlpha;
  uniform float uPixelRatio;
  uniform float uDim;
  uniform float uBoost;
  void main() {
    vColor = aColor;
    vAlpha = aAlpha * uDim * uBoost;
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = clamp(aSize * uPixelRatio, 3.0, 112.0);
  }
`;

const POINT_FRAG = `
  precision mediump float;
  varying vec3 vColor;
  varying float vAlpha;
  void main() {
    vec2 p = gl_PointCoord * 2.0 - 1.0;
    float r = length(p);
    if (r > 1.0) discard;
    float mask = pow(smoothstep(1.0, 0.0, r), 1.5);
    float gaussian = exp(-r * r * 3.6) * mask;
    float alpha = gaussian * vAlpha;
    gl_FragColor = vec4(vColor * alpha, alpha);
  }
`;

const STAR_VERT = `
  attribute float aSize;
  attribute float aBright;
  attribute float aFlare;
  attribute vec3 aTint;
  varying float vBright;
  varying vec3 vTint;
  uniform float uPixelRatio;
  void main() {
    vBright = aBright;
    vTint = aTint;
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = clamp(aSize * aFlare * uPixelRatio, 8.0, 120.0);
  }
`;

const STAR_FRAG = `
  precision mediump float;
  varying float vBright;
  varying vec3 vTint;
  void main() {
    vec2 p = gl_PointCoord * 2.0 - 1.0;
    float r = length(p);
    if (r > 1.0) discard;
    float core = pow(smoothstep(0.16, 0.0, r), 1.35);
    float axis = exp(-pow(abs(p.y) * 22.0, 2.0)) * smoothstep(1.0, 0.12, abs(p.x));
    axis += exp(-pow(abs(p.x) * 22.0, 2.0)) * smoothstep(1.0, 0.12, abs(p.y));
    float diag = min(abs(p.x - p.y), abs(p.x + p.y));
    float shortSpike = exp(-pow(diag * 18.0, 2.0)) * smoothstep(0.48, 0.05, r) * 0.42;
    float halo = exp(-r * r * 4.4) * 0.2;
    float spikes = (axis * 0.82 + shortSpike) * vBright;
    float alpha = clamp(core + spikes + halo * vBright, 0.0, 1.0);
    vec3 col = mix(vTint, vec3(1.0, 0.98, 0.94), clamp(core * 1.4 + axis * 0.35, 0.0, 1.0));
    gl_FragColor = vec4(col * alpha, alpha);
  }
`;

const BLOOM_VERT = `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = vec4(position.xy, 0.0, 1.0);
  }
`;

const BLOOM_FRAG = `
  precision mediump float;
  varying vec2 vUv;
  uniform sampler2D tScene;
  uniform vec2 uTexel;
  uniform float uExposure;
  uniform float uBloom;
  uniform float uThreshold;

  float aces1(float x) {
    x = max(x, 0.0);
    return clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0);
  }
  void main() {
    vec4 center = texture2D(tScene, vUv);
    vec3 rgb = center.rgb;
    vec2 step = uTexel * 2.5;
    vec3 glow = vec3(0.0);
    vec2 taps[4];
    taps[0] = vec2(step.x, 0.0);
    taps[1] = vec2(-step.x, 0.0);
    taps[2] = vec2(0.0, step.y);
    taps[3] = vec2(0.0, -step.y);
    for (int i = 0; i < 4; i++) {
      vec4 s = texture2D(tScene, vUv + taps[i]);
      float sa = max(s.a, 0.03);
      vec3 sampleStraight = s.rgb / sa;
      float p = max(sampleStraight.r, max(sampleStraight.g, sampleStraight.b));
      float w = smoothstep(uThreshold, uThreshold + 0.25, p) * smoothstep(0.1, 0.35, s.a);
      glow += s.rgb * w;
    }
    rgb += glow * uBloom;
    float a = center.a;
    vec3 straight = rgb;
    if (a > 0.025) straight /= a;
    float peak = max(straight.r, max(straight.g, straight.b));
    if (peak > 0.001) {
      float mapped = aces1(peak * uExposure);
      straight *= mapped / peak;
    }
    float cover = clamp(1.0 - exp(-a * 1.65), 0.0, 0.86);
    straight = min(straight, vec3(0.97));
    gl_FragColor = vec4(straight * cover, cover);
  }
`;

function makeTexture(draw) {
  const size = 256;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  draw(canvas.getContext("2d"), size);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function beadTexture() {
  return makeTexture((ctx, size) => {
    const mid = size / 2;
    const glow = ctx.createRadialGradient(mid, mid, 0, mid, mid, mid * 0.55);
    glow.addColorStop(0, "rgba(255,252,246,1)");
    glow.addColorStop(0.28, "rgba(255,236,206,0.75)");
    glow.addColorStop(1, "rgba(255,220,170,0)");
    ctx.fillStyle = glow;
    ctx.fillRect(0, 0, size, size);
  });
}

function starTexture() {
  return makeTexture((ctx, size) => {
    const mid = size / 2;
    const halo = ctx.createRadialGradient(mid, mid, 0, mid, mid, mid * 0.62);
    halo.addColorStop(0, "rgba(255,252,248,1)");
    halo.addColorStop(0.07, "rgba(255,248,236,0.95)");
    halo.addColorStop(0.16, "rgba(255,236,210,0.35)");
    halo.addColorStop(0.42, "rgba(255,214,170,0.08)");
    halo.addColorStop(1, "rgba(255,214,170,0)");
    ctx.fillStyle = halo;
    ctx.fillRect(0, 0, size, size);
    const ray = (dx, dy, len, width, alpha) => {
      const x1 = mid + dx * len;
      const y1 = mid + dy * len;
      const grad = ctx.createLinearGradient(mid, mid, x1, y1);
      grad.addColorStop(0, `rgba(255,252,248,${alpha})`);
      grad.addColorStop(0.22, `rgba(255,246,230,${alpha * 0.55})`);
      grad.addColorStop(1, "rgba(255,246,230,0)");
      ctx.strokeStyle = grad;
      ctx.lineWidth = width;
      ctx.lineCap = "round";
      ctx.beginPath();
      ctx.moveTo(mid, mid);
      ctx.lineTo(x1, y1);
      ctx.stroke();
    };
    ray(0, -1, mid * 0.92, 1.5, 0.95);
    ray(0, 1, mid * 0.92, 1.5, 0.95);
    ray(-1, 0, mid * 0.92, 1.5, 0.95);
    ray(1, 0, mid * 0.92, 1.5, 0.95);
    ray(-0.72, -0.72, mid * 0.38, 0.8, 0.32);
    ray(0.72, -0.72, mid * 0.38, 0.8, 0.32);
    ray(-0.72, 0.72, mid * 0.38, 0.8, 0.32);
    ray(0.72, 0.72, mid * 0.38, 0.8, 0.32);
  });
}

function fallbackNebula(canvas) {
  if (canvas.parentElement) canvas.parentElement.classList.add("nebula-fallback");
  return {
    setData() {},
    resize() {},
    highlight() { return { mounted: false, nodeIds: [] }; },
    screenPoint() { return null; },
    focus() {},
    setMode() {},
    dispose() {},
  };
}

function bezier(a, b, lift) {
  const mid = a.clone().add(b).multiplyScalar(0.5);
  const dir = b.clone().sub(a);
  const side = new THREE.Vector3(-dir.z, 0, dir.x);
  if (side.lengthSq() > 1e-6) side.normalize().multiplyScalar(dir.length() * 0.22);
  mid.add(side);
  mid.y += lift;
  const points = [];
  for (let i = 0; i <= 36; i += 1) {
    const t = i / 36;
    const u = 1 - t;
    points.push(a.clone().multiplyScalar(u * u).add(mid.clone().multiplyScalar(2 * u * t)).add(b.clone().multiplyScalar(t * t)));
  }
  return points;
}

function paletteColor(index, slot) {
  const row = PALETTES[index % PALETTES.length];
  const rgb = slot === 0 ? row.core : slot === 1 ? row.mid : row.edge;
  return (Math.round(Math.min(1, rgb[0]) * 255) << 16) | (Math.round(Math.min(1, rgb[1]) * 255) << 8) | Math.round(Math.min(1, rgb[2]) * 255);
}

function hash31(ix, iy, iz) {
  const n = Math.sin(ix * 127.1 + iy * 311.7 + iz * 74.7) * 43758.5453123;
  return n - Math.floor(n);
}

function noise3(x, y, z) {
  const ix = Math.floor(x);
  const iy = Math.floor(y);
  const iz = Math.floor(z);
  const fx = x - ix;
  const fy = y - iy;
  const fz = z - iz;
  const ux = fx * fx * (3 - 2 * fx);
  const uy = fy * fy * (3 - 2 * fy);
  const uz = fz * fz * (3 - 2 * fz);
  let acc = 0;
  for (let dz = 0; dz <= 1; dz += 1) {
    for (let dy = 0; dy <= 1; dy += 1) {
      for (let dx = 0; dx <= 1; dx += 1) {
        const w = (dx ? ux : 1 - ux) * (dy ? uy : 1 - uy) * (dz ? uz : 1 - uz);
        acc += w * hash31(ix + dx, iy + dy, iz + dz);
      }
    }
  }
  return acc;
}

function fbm3(x, y, z) {
  let value = 0;
  let amplitude = 0.5;
  let frequency = 1;
  for (let octave = 0; octave < 4; octave += 1) {
    value += amplitude * noise3(x * frequency, y * frequency, z * frequency);
    frequency *= 2.03;
    amplitude *= 0.5;
  }
  return value;
}

function mix3(a, b, t) {
  return [
    a[0] + (b[0] - a[0]) * t,
    a[1] + (b[1] - a[1]) * t,
    a[2] + (b[2] - a[2]) * t,
  ];
}

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

function sampleCloud(index, weight, fresh) {
  const palette = PALETTES[index % PALETTES.length];
  const next = mulberry32((index + 1) * 9973 + 11);
  const rnd = () => next() || 1e-7;
  const gauss = () => Math.sqrt(-2 * Math.log(rnd())) * Math.cos(Math.PI * 2 * rnd());
  const sx = (3.15 + (index % 3) * 0.85) * weight;
  const sy = (1.25 + ((index * 2) % 3) * 0.48) * weight;
  const sz = (0.78 + (index % 2) * 0.32) * weight;
  const shear = 0.48 * Math.sin(index * 1.37);
  const seed = index * 2.7 + 1.3;
  const positions = [];
  const colors = [];
  const sizes = [];
  const alphas = [];
  const target = 2000;
  let tries = 0;
  while (positions.length / 3 < target && tries < target * 16) {
    tries += 1;
    const x0 = gauss() * sx;
    const y0 = gauss() * sy;
    const z0 = gauss() * sz;
    const x = x0 + shear * y0;
    const y = y0 + Math.sin(x0 * 0.55 + index) * 0.55 * weight;
    const z = z0;
    const r = Math.hypot(x / sx, y / sy, z / Math.max(0.25, sz));
    if (r > 2.05) continue;
    const n = fbm3(x * 0.2 + seed, y * 0.26 + seed * 1.4, z * 0.28 + 2);
    const ridge = 1 - Math.abs(fbm3(x * 0.42 + 3.1, y * 0.5 + seed, z * 0.36) * 2 - 1);
    const lane = Math.sin(x * 0.42 + index * 0.7) * 0.7 * weight + Math.sin(z * 1.3) * 0.18 * weight;
    const dust = Math.exp(-((y - lane) * (y - lane)) / (0.22 * weight * weight + 0.08));
    const field = (0.18 + ridge * ridge * 1.05) * (0.4 + n) * (1 - dust * 0.9);
    const gate = Math.exp(-r * r * 0.24);
    if (rnd() > Math.min(0.94, field * gate * 2.05)) continue;
    positions.push(x, y, z);
    const dist = Math.min(1, r / 1.45);
    const hue = Math.min(1, Math.max(0, fbm3(x * 0.16 + 8.2, y * 0.16, z * 0.2 + index)));
    const flank = mix3(palette.edge, palette.wisp, hue);
    const body = mix3(flank, palette.mid, Math.min(1, ridge));
    const col = mix3(body, palette.core, (1 - dist) ** 1.4 * 0.9);
    colors.push(col[0], col[1], col[2]);
    sizes.push(28 + rnd() * 40);
    alphas.push(0.09 + rnd() * 0.11);
  }
  let reach = 0;
  for (let arm = 0; arm < 2; arm += 1) {
    const ang = index * 0.85 + arm * 2.15;
    const len = (1.35 + (arm === 0 ? 0.55 : 0.15) + rnd() * 0.25) * weight;
    reach = Math.max(reach, len);
    const curl = (arm % 2 ? 1 : -1) * (0.55 + rnd() * 0.45);
    for (let i = 0; i < 72; i += 1) {
      const t = rnd() ** 0.72;
      const spread = (0.08 + t * 0.45) * (0.22 + rnd() * 0.3) * weight;
      const along = t * len;
      const side = gauss() * spread;
      const x = Math.cos(ang) * along + Math.cos(ang + 1.15) * side + Math.sin(along * curl) * 0.42 * weight;
      const y = Math.sin(ang) * along * 0.58 + Math.sin(ang + 0.4) * side * 0.35;
      const z = gauss() * spread * 0.35;
      positions.push(x, y, z);
      const tint = mix3(palette.mid, palette.wisp, 0.3 + t * 0.7);
      const fade = mix3(tint, palette.edge, t * 0.75);
      colors.push(fade[0], fade[1], fade[2]);
      sizes.push(6 + (1 - t) * 8);
      alphas.push(0.012 + (1 - t) * 0.018);
    }
  }
  for (let i = 0; i < 340; i += 1) {
    positions.push(gauss() * 0.62 * weight, gauss() * 0.4 * weight, gauss() * 0.22 * weight);
    colors.push(
      Math.min(1.75, palette.core[0] * 1.4),
      Math.min(1.4, palette.core[1] * 1.3),
      Math.min(1.4, palette.core[2] * 1.3),
    );
    sizes.push(18 + rnd() * 22);
    alphas.push(0.14 + rnd() * 0.1);
  }
  if (fresh) {
    for (let i = 0; i < 150; i += 1) {
      const ang = -0.5 + rnd() * 2.15;
      const rad = sx * (1.05 + rnd() * 0.16);
      positions.push(Math.cos(ang) * rad, Math.sin(ang) * rad * 0.62, gauss() * 0.18 * weight);
      colors.push(1.3, 0.98, 0.58);
      sizes.push(8 + rnd() * 10);
      alphas.push(0.03 + rnd() * 0.03);
    }
  }
  return {
    positions,
    colors,
    sizes,
    alphas,
    radius: Math.max(sx, sy) * 1.15 + reach * 0.72,
  };
}

export function createNebula(canvas, hooks) {
  const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha: true,
      premultipliedAlpha: true,
      powerPreference: "high-performance",
    });
  } catch (error) {
    return fallbackNebula(canvas);
  }
  if (!renderer.getContext()) return fallbackNebula(canvas);
  renderer.setClearColor(0x000000, 0);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  if (THREE.LinearSRGBColorSpace) renderer.outputColorSpace = THREE.LinearSRGBColorSpace;
  renderer.toneMapping = THREE.NoToneMapping;

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(34, 1, 0.1, 400);
  const look = new THREE.Vector3();
  const lookTarget = new THREE.Vector3();
  const camTarget = new THREE.Vector3(0, 0, 32);
  camera.position.copy(camTarget);

  const gl = renderer.getContext();
  const floatTarget = Boolean(gl.getExtension("EXT_color_buffer_float") || gl.getExtension("EXT_color_buffer_half_float"));
  const sceneTarget = new THREE.WebGLRenderTarget(8, 8, {
    format: THREE.RGBAFormat,
    type: floatTarget ? THREE.HalfFloatType : THREE.UnsignedByteType,
    depthBuffer: false,
    stencilBuffer: false,
  });
  if (THREE.LinearSRGBColorSpace) sceneTarget.texture.colorSpace = THREE.LinearSRGBColorSpace;
  const bloomUniforms = {
    tScene: { value: sceneTarget.texture },
    uTexel: { value: new THREE.Vector2(1 / 8, 1 / 8) },
    uExposure: { value: 0.78 },
    uBloom: { value: 0.06 },
    uThreshold: { value: 0.86 },
  };
  const bloomMaterial = new THREE.ShaderMaterial({
    uniforms: bloomUniforms,
    vertexShader: BLOOM_VERT,
    fragmentShader: BLOOM_FRAG,
    transparent: true,
    depthTest: false,
    depthWrite: false,
    premultipliedAlpha: true,
    blending: THREE.NormalBlending,
  });
  const bloomScene = new THREE.Scene();
  const bloomCamera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  bloomScene.add(new THREE.Mesh(new THREE.PlaneGeometry(2, 2), bloomMaterial));

  const sprite = starTexture();
  const bead = beadTexture();
  const world = new THREE.Group();
  scene.add(world);
  const overlay = new THREE.Scene();
  let starPoints = null;
  let sparkPoints = null;
  const starIds = [];
  const pickables = [];
  const factMeshes = new Map();
  const expertMeshes = new Map();
  const expertClouds = new Map();
  const nodePos = new Map();
  const filaments = [];
  const gasMats = [];
  const labels = [];
  let labelLayer = null;
  let ingress = null;
  let framed = null;
  let userMoved = false;
  let recall = null;
  let mode = "full";
  let running = true;
  let looping = false;
  let frameCount = 0;
  const debugInfo = gl.getExtension("WEBGL_debug_renderer_info");
  const rendererName = debugInfo ? String(gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL) || "") : "";
  const software = /swiftshader|llvmpipe|softpipe/i.test(rendererName);

  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  let dragging = false;
  let moved = 0;
  let lastX = 0;
  let lastY = 0;

  function disposeNode(obj) {
    obj.traverse((node) => {
      if (node.geometry) node.geometry.dispose();
      const mats = node.material ? [].concat(node.material) : [];
      mats.forEach((material) => {
        if (material.map && material.map !== sprite && material.map !== bead) material.map.dispose();
        material.dispose();
      });
    });
  }

  function clearWorld() {
    [world, overlay].forEach((root) => {
      while (root.children.length) disposeNode(root.children.pop());
    });
    starPoints = null;
    sparkPoints = null;
    starIds.length = 0;
    pickables.length = 0;
    factMeshes.clear();
    expertMeshes.clear();
    expertClouds.clear();
    nodePos.clear();
    filaments.length = 0;
    gasMats.length = 0;
    labels.length = 0;
    ingress = null;
    if (labelLayer) labelLayer.replaceChildren();
    recall = null;
    framed = null;
    userMoved = false;
  }

  function makeCloud(position, index, name, expert, weight, fresh) {
    const group = new THREE.Group();
    group.position.copy(position);
    group.rotation.x = 0.28 + index * 0.31;
    group.rotation.z = -0.4 + index * 0.37;
    const cloud = sampleCloud(index, weight, fresh);
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(cloud.positions, 3));
    geometry.setAttribute("aColor", new THREE.Float32BufferAttribute(cloud.colors, 3));
    geometry.setAttribute("aSize", new THREE.Float32BufferAttribute(cloud.sizes, 1));
    geometry.setAttribute("aAlpha", new THREE.Float32BufferAttribute(cloud.alphas, 1));
    const material = new THREE.ShaderMaterial({
      uniforms: {
        uPixelRatio: { value: renderer.getPixelRatio() },
        uDim: { value: 1 },
        uBoost: { value: 1 },
      },
      vertexShader: POINT_VERT,
      fragmentShader: POINT_FRAG,
      transparent: true,
      depthWrite: false,
      depthTest: false,
      blending: THREE.AdditiveBlending,
      premultipliedAlpha: true,
    });
    gasMats.push(material);
    const points = new THREE.Points(geometry, material);
    points.frustumCulled = false;
    points.renderOrder = 1;
    group.add(points);
    const pick = new THREE.Mesh(
      new THREE.SphereGeometry(Math.max(4.8, cloud.radius * 0.62), 10, 8),
      new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false, color: 0x000000 }),
    );
    pick.userData = { kind: "expert", expertName: name, expert };
    group.add(pick);
    pickables.push(pick);
    group.userData = {
      kind: "expert",
      expertName: name,
      expert,
      baseScale: 1,
      spin: index * 0.9,
      radius: cloud.radius,
      fresh,
      weight,
      material,
    };
    world.add(group);
    expertClouds.set(name, group);
    expertMeshes.set(name, group);
    return group;
  }

  function ribbonGeometry(points, halfWidth) {
    const positions = [];
    const uvs = [];
    for (let i = 0; i < points.length; i += 1) {
      const prev = points[Math.max(0, i - 1)];
      const next = points[Math.min(points.length - 1, i + 1)];
      const side = new THREE.Vector3(-(next.y - prev.y), next.x - prev.x, 0);
      if (side.lengthSq() < 1e-8) side.set(0, 1, 0);
      side.normalize().multiplyScalar(halfWidth);
      const left = points[i].clone().add(side);
      const right = points[i].clone().sub(side);
      positions.push(left.x, left.y, left.z, right.x, right.y, right.z);
      const u = i / Math.max(1, points.length - 1);
      uvs.push(u, 0, u, 1);
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
    geo.setAttribute("uv", new THREE.Float32BufferAttribute(uvs, 2));
    const indices = [];
    for (let i = 0; i < points.length - 1; i += 1) {
      const offset = i * 2;
      indices.push(offset, offset + 1, offset + 2, offset + 1, offset + 3, offset + 2);
    }
    geo.setIndex(indices);
    return geo;
  }

  function addFilament(a, b, color, gain) {
    const points = bezier(a, b, 2.2 + (filaments.length % 3) * 1.15);
    const geo = ribbonGeometry(points, 0.14);
    const tint = new THREE.Color(color);
    const material = new THREE.ShaderMaterial({
      uniforms: {
        uColor: { value: new THREE.Vector3(tint.r, tint.g, tint.b) },
        uGain: { value: gain == null ? 0.3 : gain },
      },
      vertexShader: GAS_VERT,
      fragmentShader: `
        precision mediump float;
        varying vec2 vUv;
        uniform vec3 uColor;
        uniform float uGain;
        void main() {
          float across = pow(smoothstep(0.0, 0.5, vUv.y) * smoothstep(1.0, 0.5, vUv.y), 1.15);
          float along = smoothstep(0.0, 0.1, vUv.x) * smoothstep(1.0, 0.9, vUv.x);
          float alpha = across * along * uGain;
          gl_FragColor = vec4(uColor * alpha, alpha);
        }
      `,
      transparent: true,
      depthWrite: false,
      depthTest: false,
      side: THREE.DoubleSide,
      premultipliedAlpha: true,
      blending: THREE.AdditiveBlending,
    });
    const line = new THREE.Mesh(geo, material);
    line.renderOrder = 2;
    overlay.add(line);
    const beads = [];
    for (let i = 0; i < 3; i += 1) {
      const mote = new THREE.Sprite(new THREE.SpriteMaterial({
        map: bead,
        transparent: true,
        opacity: 0.9,
        depthWrite: false,
        depthTest: false,
        blending: THREE.AdditiveBlending,
        premultipliedAlpha: true,
      }));
      mote.material.color.r = Math.min(1.6, tint.r * 2.2);
      mote.material.color.g = Math.min(1.5, tint.g * 2.1);
      mote.material.color.b = Math.min(1.35, tint.b * 1.8);
      mote.scale.setScalar(0.22);
      mote.renderOrder = 4;
      mote.userData.phase = i / 3;
      overlay.add(mote);
      beads.push(mote);
    }
    const filament = { points, beads, material, mesh: line, source: "", target: "", hot: false, role: "link" };
    filaments.push(filament);
    return filament;
  }

  function dropIngress() {
    if (!ingress) return;
    const index = filaments.indexOf(ingress);
    if (index >= 0) filaments.splice(index, 1);
    if (ingress.mesh) {
      overlay.remove(ingress.mesh);
      ingress.mesh.geometry.dispose();
      ingress.mesh.material.dispose();
    }
    (ingress.beads || []).forEach((mote) => {
      overlay.remove(mote);
      mote.material.dispose();
    });
    ingress = null;
  }

  function ensureLabelLayer() {
    const host = canvas.parentElement;
    if (!host) return null;
    host.querySelectorAll(".nebula-labels").forEach((node) => {
      if (node !== labelLayer) node.remove();
    });
    if (!labelLayer || labelLayer.parentElement !== host) {
      labelLayer = document.createElement("div");
      labelLayer.className = "nebula-labels";
      host.appendChild(labelLayer);
    }
    return labelLayer;
  }

  const scratch = [new THREE.Vector3(), new THREE.Vector3(), new THREE.Vector3()];
  let framedPage = null;

  function projectScreen(vector, width, height, target) {
    target.copy(vector).project(camera);
    return {
      x: (target.x * 0.5 + 0.5) * width,
      y: (-target.y * 0.5 + 0.5) * height,
    };
  }

  function leaderSvg() {
    const layer = ensureLabelLayer();
    if (!layer) return null;
    let svg = layer.querySelector(".nebula-leaders");
    if (!svg) {
      svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("class", "nebula-leaders");
      svg.setAttribute("aria-hidden", "true");
      layer.insertBefore(svg, layer.firstChild);
    }
    return svg;
  }

  function fillLabel(item) {
    let name = (item.expert && (item.expert.display_name || item.expert.name)) || "";
    if (window.i18n && window.i18n.getLocale() === "en" && window.i18n.foreignName) name = window.i18n.foreignName(name);
    const countText = window.i18n && window.i18n.t
      ? window.i18n.t("nebula.count", { n: item.count })
      : String(item.count);
    const nameEl = item.el.querySelector(".name");
    const metaEl = item.el.querySelector(".meta");
    const tagEl = item.el.querySelector(".tag");
    if (nameEl) nameEl.textContent = name;
    if (metaEl) metaEl.textContent = ` · ${countText}`;
    if (!tagEl) return;
    if (item.fresh) {
      const word = window.i18n && window.i18n.t ? window.i18n.t("nebula.new") : "New";
      tagEl.hidden = false;
      tagEl.textContent = ` · ${word}`;
    } else {
      tagEl.hidden = true;
      tagEl.textContent = "";
    }
  }

  function refreshLabels() {
    labels.forEach((item) => fillLabel(item));
    placeLabels();
  }

  function cloudMetrics(group, width, height) {
    group.getWorldPosition(scratch[0]);
    const radius = group.userData.radius || 8;
    const center = projectScreen(scratch[0], width, height, scratch[1]);
    const cx = center.x;
    const cy = center.y;
    scratch[2].set(scratch[0].x + radius, scratch[0].y, scratch[0].z);
    const rimX = projectScreen(scratch[2], width, height, scratch[1]);
    scratch[2].set(scratch[0].x, scratch[0].y + radius * 0.72, scratch[0].z);
    const rimY = projectScreen(scratch[2], width, height, scratch[1]);
    const screenR = Math.max(
      Math.hypot(rimX.x - cx, rimX.y - cy),
      Math.hypot(rimY.x - cx, rimY.y - cy),
    ) + 16;
    let dirx = scratch[0].x;
    let diry = scratch[0].y;
    const dlen = Math.hypot(dirx, diry);
    if (dlen < 1e-4) {
      dirx = 0;
      diry = -1;
    } else {
      dirx /= dlen;
      diry /= dlen;
    }
    scratch[2].set(scratch[0].x + dirx, scratch[0].y + diry, scratch[0].z);
    const further = projectScreen(scratch[2], width, height, scratch[1]);
    let ux = further.x - cx;
    let uy = further.y - cy;
    const olen = Math.hypot(ux, uy) || 1;
    ux /= olen;
    uy /= olen;
    return { cx, cy, screenR, ux, uy };
  }

  function clampBox(x, y, hw, hh, width, height, pad) {
    const minX = pad + hw;
    const maxX = Math.max(minX, width - pad - hw);
    const minY = pad + hh;
    const maxY = Math.max(minY, height - pad - hh);
    return {
      x: Math.min(maxX, Math.max(minX, x)),
      y: Math.min(maxY, Math.max(minY, y)),
    };
  }

  function scoreBox(box, item, clouds, placed, prefer) {
    let penalty = 0;
    placed.forEach((spot) => {
      const ox = item.hw + spot.hw + 10 - Math.abs(box.x - spot.x);
      const oy = item.hh + spot.hh + 8 - Math.abs(box.y - spot.y);
      if (ox > 0 && oy > 0) penalty += ox * oy;
    });
    clouds.forEach((cloud) => {
      const dx = Math.max(Math.abs(box.x - cloud.cx) - item.hw, 0);
      const dy = Math.max(Math.abs(box.y - cloud.cy) - item.hh, 0);
      // 全页取景下云团互相重叠。标签必须离开自己的星团，邻云只避开星核。
      const avoid = cloud === item ? cloud.screenR + 6 : cloud.screenR * 0.42;
      const intrusion = avoid - Math.hypot(dx, dy);
      if (intrusion > 0) penalty += intrusion * intrusion;
    });
    return penalty * 6 + Math.hypot(box.x - item.cx, box.y - item.cy) * 0.08 - prefer * 24;
  }

  function appendLeader(svg, item, box) {
    const vx = box.x - item.cx;
    const vy = box.y - item.cy;
    const vlen = Math.hypot(vx, vy) || 1;
    const ux = vx / vlen;
    const uy = vy / vlen;
    const along = Math.min(item.hw / (Math.abs(ux) || 1e-4), item.hh / (Math.abs(uy) || 1e-4));
    const x1 = box.x - ux * along;
    const y1 = box.y - uy * along;
    const x2 = item.cx + ux * item.screenR;
    const y2 = item.cy + uy * item.screenR;
    if (Math.hypot(x2 - x1, y2 - y1) < 8) return;
    const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
    line.setAttribute("x1", x1.toFixed(1));
    line.setAttribute("y1", y1.toFixed(1));
    line.setAttribute("x2", x2.toFixed(1));
    line.setAttribute("y2", y2.toFixed(1));
    svg.appendChild(line);
  }

  function placeLabels() {
    const width = canvas.clientWidth || 0;
    const height = canvas.clientHeight || 0;
    const svg = leaderSvg();
    if (svg) {
      svg.setAttribute("viewBox", `0 0 ${Math.max(1, width)} ${Math.max(1, height)}`);
      svg.setAttribute("width", String(Math.max(1, width)));
      svg.setAttribute("height", String(Math.max(1, height)));
      svg.replaceChildren();
    }
    if (width < 40 || height < 40 || !labels.length) return;
    const pad = 12;
    const maxLabel = Math.max(96, width - pad * 2);
    labels.forEach((item) => { item.el.style.maxWidth = `${maxLabel}px`; });
    const clouds = labels.map((item) => {
      const screen = cloudMetrics(item.group, width, height);
      return {
        ...item,
        ...screen,
        hw: Math.max(8, item.el.offsetWidth / 2),
        hh: Math.max(8, item.el.offsetHeight / 2),
      };
    });
    const midX = clouds.reduce((sum, cloud) => sum + cloud.cx, 0) / clouds.length;
    const midY = clouds.reduce((sum, cloud) => sum + cloud.cy, 0) / clouds.length;
    const placed = [];
    clouds.slice().sort((a, b) => (
      Math.hypot(b.cx - midX, b.cy - midY) - Math.hypot(a.cx - midX, a.cy - midY)
    )).forEach((item) => {
      const base = Math.atan2(item.uy, item.ux);
      let best = null;
      const consider = (x, y, prefer) => {
        const box = clampBox(x, y, item.hw, item.hh, width, height, pad);
        const score = scoreBox(box, item, clouds, placed, prefer);
        if (!best || score < best.score) best = { x: box.x, y: box.y, score };
      };
      for (let i = 0; i < 24; i += 1) {
        const delta = (i % 2 === 0 ? 1 : -1) * Math.ceil(i / 2) * (Math.PI / 12);
        const ang = base + delta;
        const ux = Math.cos(ang);
        const uy = Math.sin(ang);
        const support = item.hw * Math.abs(ux) + item.hh * Math.abs(uy);
        const dist = item.screenR + 14 + support;
        const prefer = ux * item.ux + uy * item.uy;
        consider(item.cx + ux * dist, item.cy + uy * dist, prefer);
        consider(item.cx + ux * (dist + 48), item.cy + uy * (dist + 48), prefer);
      }
      consider(item.cx, pad + item.hh, 0.15);
      consider(item.cx, height - pad - item.hh, 0.15);
      consider(pad + item.hw, item.cy, 0.15);
      consider(width - pad - item.hw, item.cy, 0.15);
      const spanX = Math.max(1, width - pad * 2 - item.hw * 2);
      const spanY = Math.max(1, height - pad * 2 - item.hh * 2);
      for (let gy = 0; gy < 5; gy += 1) {
        for (let gx = 0; gx < 4; gx += 1) {
          consider(pad + item.hw + spanX * (gx / 3), pad + item.hh + spanY * (gy / 4), 0);
        }
      }
      if (!best) best = clampBox(item.cx, item.cy, item.hw, item.hh, width, height, pad);
      placed.push({ x: best.x, y: best.y, hw: item.hw, hh: item.hh });
      item.el.style.left = `${best.x}px`;
      item.el.style.top = `${best.y}px`;
      item.el.dataset.cloud = `${item.cx.toFixed(1)},${item.cy.toFixed(1)},${item.screenR.toFixed(1)}`;
      item.el.classList.toggle("lit", Boolean(recall && recall.expertName === item.group.userData.expertName));
      if (svg) appendLeader(svg, item, best);
    });
  }

  function makePoints(positions, sizes, brights, flares, tints, order) {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute("aSize", new THREE.BufferAttribute(sizes, 1));
    geometry.setAttribute("aBright", new THREE.BufferAttribute(brights, 1));
    geometry.setAttribute("aFlare", new THREE.BufferAttribute(flares, 1));
    geometry.setAttribute("aTint", new THREE.BufferAttribute(tints, 3));
    geometry.userData.baseBright = Array.from(brights);
    const material = new THREE.ShaderMaterial({
      uniforms: { uPixelRatio: { value: renderer.getPixelRatio() } },
      vertexShader: STAR_VERT,
      fragmentShader: STAR_FRAG,
      transparent: true,
      depthWrite: false,
      depthTest: false,
      blending: THREE.AdditiveBlending,
      premultipliedAlpha: true,
    });
    const points = new THREE.Points(geometry, material);
    points.frustumCulled = false;
    points.renderOrder = order;
    overlay.add(points);
    return points;
  }

  function setData(data) {
    clearWorld();
    const experts = data.experts || [];
    const facts = data.facts || [];
    const conversations = data.conversations || [];
    const links = (data.links || []).slice();
    const counts = new Map();
    facts.forEach((fact) => {
      if (fact.superseded) return;
      counts.set(fact.expert, (counts.get(fact.expert) || 0) + 1);
    });
    const maxCount = Math.max(1, ...counts.values());
    const count = Math.max(1, experts.length);
    const cols = count <= 1 ? 1 : Math.min(count, count <= 4 ? 2 : 3);
    const rows = Math.ceil(count / cols);
    experts.forEach((expert, index) => {
      const active = counts.get(expert.name) || 0;
      const fresh = Boolean(expert.writable && expert.explicit);
      let weight = 1.05 + 0.55 * Math.sqrt(active / maxCount);
      if (fresh) weight = Math.max(weight, 1.2);
      const col = index % cols;
      const row = Math.floor(index / cols);
      const pos = new THREE.Vector3(
        (col - (cols - 1) / 2) * 12.4,
        ((rows - 1) / 2 - row) * 10.6,
        (index % 2) * 0.28,
      );
      nodePos.set(expert.id || `expert:${expert.name}`, pos.clone());
      makeCloud(pos, index, expert.name, expert, weight, fresh);
    });

    const grouped = new Map();
    facts.forEach((fact) => {
      if (!grouped.has(fact.expert)) grouped.set(fact.expert, []);
      grouped.get(fact.expert).push(fact);
    });
    const starPositions = [];
    const starSizes = [];
    const starBrights = [];
    const starFlares = [];
    const starTints = [];
    grouped.forEach((group, name) => {
      const origin = nodePos.get(`expert:${name}`) || new THREE.Vector3();
      const cloud = expertClouds.get(name);
      const weight = cloud ? cloud.userData.weight : 1;
      const tint = cloud && cloud.userData.fresh ? [1.0, 0.9, 0.62] : [1.0, 0.9, 0.74];
      group.forEach((fact, index) => {
        const golden = index * 2.399963;
        const ring = (0.55 + Math.sqrt((index + 0.5) / group.length) * 1.55) * weight;
        const pos = origin.clone().add(new THREE.Vector3(
          Math.cos(golden) * ring,
          Math.sin(golden * 1.17) * ring * 0.62,
          ((index % 5) - 2) * 0.16,
        ));
        nodePos.set(fact.id, pos.clone());
        const hits = Number(fact.recall_hits) || 0;
        const recency = (index + 1) / group.length;
        const bright = fact.superseded ? 0.22 : Math.min(1, 0.42 + Math.min(0.38, hits * 0.2) + recency * 0.28);
        starPositions.push(pos.x, pos.y, pos.z);
        starSizes.push(fact.superseded ? 18 : 36 + bright * 20);
        starBrights.push(fact.superseded ? 0.28 : 0.48 + bright * 0.52);
        starFlares.push(1);
        starTints.push(tint[0], tint[1], tint[2]);
        starIds.push(fact.id);
        const pick = new THREE.Sprite(new THREE.SpriteMaterial({
          transparent: true,
          opacity: 0,
          depthWrite: false,
          depthTest: false,
          color: 0xffffff,
        }));
        pick.scale.setScalar(1.4);
        pick.position.copy(pos);
        pick.userData = { kind: "fact", fact, baseScale: 1.4 };
        world.add(pick);
        pickables.push(pick);
        factMeshes.set(fact.id, pick);
      });
    });
    if (starPositions.length) {
      starPoints = makePoints(
        new Float32Array(starPositions),
        new Float32Array(starSizes),
        new Float32Array(starBrights),
        new Float32Array(starFlares),
        new Float32Array(starTints),
        8,
      );
    }

    const convDots = [];
    conversations.forEach((conv, index) => {
      const related = links.filter((link) => link.kind === "source" && (link.source === conv.id || link.target === conv.id));
      const anchor = new THREE.Vector3();
      let count = 0;
      related.forEach((link) => {
        const other = link.source === conv.id ? link.target : link.source;
        const pos = nodePos.get(other);
        if (pos) {
          anchor.add(pos);
          count += 1;
        }
      });
      if (!count) return;
      anchor.multiplyScalar(1 / count);
      const pos = anchor.clone().add(new THREE.Vector3(-2.4 - (index % 2) * 0.45, (index % 3) * 0.35 - 0.4, 0.15));
      nodePos.set(conv.id, pos.clone());
      convDots.push(pos);
      const pick = new THREE.Sprite(new THREE.SpriteMaterial({
        transparent: true,
        opacity: 0,
        depthWrite: false,
        depthTest: false,
        color: 0xffffff,
      }));
      pick.scale.setScalar(0.9);
      pick.position.copy(pos);
      pick.userData = { kind: "conversation", conversation: conv };
      world.add(pick);
      pickables.push(pick);
    });
    if (convDots.length) {
      const n = convDots.length;
      const positions = new Float32Array(n * 3);
      const sizes = new Float32Array(n);
      const brights = new Float32Array(n);
      const flares = new Float32Array(n);
      const tints = new Float32Array(n * 3);
      convDots.forEach((pos, index) => {
        positions.set([pos.x, pos.y, pos.z], index * 3);
        sizes[index] = 15;
        brights[index] = 0.92;
        flares[index] = 1;
        tints.set([0.62, 0.84, 1.0], index * 3);
      });
      const nodes = makePoints(positions, sizes, brights, flares, tints, 7);
      nodes.userData.role = "conversation";
    }

    links.forEach((link) => {
      if (link.kind === "source") {
        const fact = nodePos.get(link.source);
        const conv = nodePos.get(link.target);
        if (!fact || !conv) return;
        const filament = addFilament(conv, fact, 0xf6e2b4, 0.14);
        filament.source = link.target;
        filament.target = link.source;
        filament.role = "source";
        return;
      }
      if (link.kind !== "entity" && link.kind !== "semantic" && link.kind !== "supersede") return;
      const a = nodePos.get(link.source);
      const b = nodePos.get(link.target);
      if (!a || !b) return;
      const filament = addFilament(a, b, link.kind === "supersede" ? 0x9aa3b3 : 0xd7b56a, link.kind === "entity" ? 0.16 : 0.12);
      filament.source = link.source;
      filament.target = link.target;
      filament.role = link.kind;
    });

    const layer = ensureLabelLayer();
    if (layer) layer.replaceChildren();
    experts.forEach((expert) => {
      const group = expertClouds.get(expert.name);
      if (!group || !layer) return;
      const el = document.createElement("div");
      el.className = `nebula-label${group.userData.fresh ? " fresh" : ""}`;
      const name = document.createElement("span");
      name.className = "name";
      const meta = document.createElement("span");
      meta.className = "meta";
      const tag = document.createElement("span");
      tag.className = "tag";
      tag.hidden = true;
      el.append(name, meta, tag);
      const item = {
        el,
        group,
        expert,
        count: counts.get(expert.name) || 0,
        fresh: Boolean(group.userData.fresh),
      };
      fillLabel(item);
      layer.appendChild(el);
      labels.push(item);
    });

    const freshGroups = [...expertClouds.values()].filter((group) => group.userData.fresh);
    if (freshGroups.length) {
      const count = freshGroups.length * 8;
      const positions = new Float32Array(count * 3);
      const sizes = new Float32Array(count);
      const brights = new Float32Array(count);
      const flares = new Float32Array(count);
      const tints = new Float32Array(count * 3);
      for (let i = 0; i < count; i += 1) {
        sizes[i] = 11 + (i % 3) * 2;
        brights[i] = 0.9;
        flares[i] = 1;
        tints.set([1.0, 0.78, 0.36], i * 3);
      }
      sparkPoints = makePoints(positions, sizes, brights, flares, tints, 6);
      sparkPoints.userData.groups = freshGroups;
    }

    const box = new THREE.Box3();
    expertClouds.forEach((group) => {
      const body = Math.max(5.2, (group.userData.radius || 8) * 0.72);
      box.expandByPoint(group.position.clone().add(new THREE.Vector3(body, body * 0.78, 0.8)));
      box.expandByPoint(group.position.clone().add(new THREE.Vector3(-body, -body * 0.78, -0.8)));
    });
    if (box.isEmpty()) box.setFromCenterAndSize(new THREE.Vector3(), new THREE.Vector3(10, 6, 8));
    const sphere = box.getBoundingSphere(new THREE.Sphere());
    framed = {
      center: sphere.center.clone(),
      radius: Math.max(8.5, sphere.radius * 1.16),
    };
    applyFrame(true);
    placeLabels();
  }

  function applyFrame(immediate) {
    if (!framed) return;
    const { center, radius } = framed;
    lookTarget.copy(center);
    const fov = camera.fov * Math.PI / 180;
    const aspect = Math.max(0.35, camera.aspect || 1);
    const distY = radius / Math.tan(fov / 2);
    const distX = radius / (Math.tan(fov / 2) * aspect);
    // 竖屏按宽度取景，云团留在画面中部，四周留一圈边，不要为了铺满高度把相机拉远。
    const portrait = aspect < 1;
    const dist = portrait ? distX * 1.28 : Math.max(distY, distX) * 1.08;
    camTarget.set(center.x, center.y, center.z + dist);
    if (immediate) {
      look.copy(lookTarget);
      camera.position.copy(camTarget);
      camera.lookAt(look);
    }
  }

  function resize() {
    const width = canvas.clientWidth || 800;
    const height = canvas.clientHeight || 600;
    const ratio = Math.min(window.devicePixelRatio || 1, mode === "dim" ? 1 : 2);
    renderer.setPixelRatio(ratio);
    renderer.setSize(width, height, false);
    const bufferW = Math.max(1, Math.floor(width * ratio));
    const bufferH = Math.max(1, Math.floor(height * ratio));
    sceneTarget.setSize(bufferW, bufferH);
    bloomUniforms.uTexel.value.set(2.2 / bufferW, 2.2 / bufferH);
    camera.aspect = width / Math.max(1, height);
    camera.updateProjectionMatrix();
    const page = Boolean(canvas.closest("#nebula-host"));
    if (framedPage !== page) {
      framedPage = page;
      userMoved = false;
    }
    if (!userMoved) applyFrame(true);
    placeLabels();
  }

  function project(nodeId) {
    const mesh = factMeshes.get(nodeId) || expertMeshes.get(String(nodeId).replace(/^expert:/, ""));
    if (!mesh) return null;
    const vector = mesh.getWorldPosition(new THREE.Vector3());
    vector.project(camera);
    const width = canvas.clientWidth || 1;
    const height = canvas.clientHeight || 1;
    return {
      x: (vector.x * 0.5 + 0.5) * width,
      y: (-vector.y * 0.5 + 0.5) * height,
    };
  }

  function restore() {
    dropIngress();
    factMeshes.forEach((mesh) => {
      mesh.scale.setScalar(mesh.userData.baseScale || 1.4);
      mesh.material.opacity = 0;
    });
    filaments.forEach((filament) => {
      filament.hot = false;
    });
  }

  function highlight(trace) {
    recall = null;
    restore();
    const mounted = Boolean(trace && trace.mounted && trace.mounted_expert);
    if (!mounted) return { mounted: false, nodeIds: [] };
    const nodeIds = (trace.matched_facts || []).map((fact) => fact.node_id).filter((id) => factMeshes.has(id));
    recall = {
      expertName: trace.mounted_expert,
      nodeIds: new Set(nodeIds),
      started: performance.now(),
    };
    const target = factMeshes.get(nodeIds[0]) || expertMeshes.get(trace.mounted_expert);
    if (target) {
      const pos = target.getWorldPosition(new THREE.Vector3());
      const from = pos.clone();
      from.x -= Math.max(8, framed ? framed.radius * 0.42 : 10);
      from.y += 1.4;
      ingress = addFilament(from, pos, 0xffe6b0, 0.86);
      ingress.hot = true;
      ingress.role = "ingress";
    }
    filaments.forEach((filament) => {
      if (filament === ingress) return;
      filament.hot = recall.nodeIds.has(filament.target) || recall.nodeIds.has(filament.source)
        || filament.target === `expert:${recall.expertName}` || filament.source === `expert:${recall.expertName}`;
    });
    return { mounted: true, nodeIds: nodeIds.length ? nodeIds : [`expert:${trace.mounted_expert}`] };
  }

  function flyTo(object) {
    if (!object) return;
    userMoved = true;
    const pos = object.getWorldPosition(new THREE.Vector3());
    lookTarget.copy(pos);
    const offset = camera.position.clone().sub(look);
    if (offset.length() < 0.1) offset.set(0, 1.2, 12);
    offset.setLength(Math.min(22, Math.max(8, offset.length() * 0.72)));
    camTarget.copy(pos).add(offset);
  }

  function hover(event) {
    const rect = canvas.getBoundingClientRect();
    pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    raycaster.setFromCamera(pointer, camera);
    const hits = raycaster.intersectObjects(pickables, false);
    if (!hits.length) {
      hooks.onHover(null);
      canvas.style.cursor = dragging ? "grabbing" : "grab";
      return;
    }
    canvas.style.cursor = "pointer";
    hooks.onHover(hits[0].object.userData, event.clientX - rect.left, event.clientY - rect.top);
  }

  const activePointers = new Map();
  let pinchDist = 0;
  function zoomBy(factor) {
    userMoved = true;
    const offset = camTarget.clone().sub(look);
    offset.setLength(Math.min(90, Math.max(6, offset.length() * factor)));
    camTarget.copy(look).add(offset);
  }
  canvas.addEventListener("pointerdown", (event) => {
    activePointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (activePointers.size >= 2) {
      const pts = [...activePointers.values()];
      pinchDist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y) || 1;
      dragging = false;
    } else {
      dragging = true;
      moved = 0;
      lastX = event.clientX;
      lastY = event.clientY;
    }
    try { canvas.setPointerCapture(event.pointerId); } catch (error) {}
  });
  canvas.addEventListener("pointermove", (event) => {
    if (activePointers.has(event.pointerId)) {
      activePointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    }
    if (activePointers.size >= 2) {
      const pts = [...activePointers.values()];
      const dist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y) || 1;
      if (pinchDist > 0) zoomBy(pinchDist / dist);
      pinchDist = dist;
      dragging = false;
      return;
    }
    if (dragging) {
      const dx = event.clientX - lastX;
      const dy = event.clientY - lastY;
      moved += Math.abs(dx) + Math.abs(dy);
      lastX = event.clientX;
      lastY = event.clientY;
      userMoved = true;
      const offset = camTarget.clone().sub(look);
      const spherical = new THREE.Spherical().setFromVector3(offset);
      spherical.theta -= dx * 0.005;
      spherical.phi = Math.min(Math.PI - 0.18, Math.max(0.18, spherical.phi + dy * 0.005));
      offset.setFromSpherical(spherical);
      camTarget.copy(look).add(offset);
    }
    hover(event);
  });
  canvas.addEventListener("pointercancel", (event) => {
    activePointers.delete(event.pointerId);
    pinchDist = 0;
    dragging = false;
  });
  canvas.addEventListener("pointerup", (event) => {
    const wasPinch = activePointers.size >= 2 || pinchDist > 0;
    activePointers.delete(event.pointerId);
    if (activePointers.size < 2) pinchDist = 0;
    dragging = false;
    if (wasPinch) return;
    if (moved < 5) {
      const rect = canvas.getBoundingClientRect();
      pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(pointer, camera);
      const hits = raycaster.intersectObjects(pickables, false);
      if (hits.length) {
        flyTo(hits[0].object);
        hooks.onSelect(hits[0].object.userData);
      }
    }
  });
  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    userMoved = true;
    const offset = camTarget.clone().sub(look);
    const next = offset.length() * (event.deltaY > 0 ? 1.08 : 0.92);
    offset.setLength(Math.min(90, Math.max(6, next)));
    camTarget.copy(look).add(offset);
  }, { passive: false });

  const clock = new THREE.Clock();
  let frozenAt = 0;
  function frame(now) {
    if (!running) return;
    if (mode === "dim") {
      looping = false;
      return;
    }
    requestAnimationFrame(frame);
    looping = true;
    if (!canvas.clientWidth || document.hidden) return;
    frameCount += 1;
    if (software && now != null && frameCount > 1 && now - frozenAt < 200) return;
    if (now != null) frozenAt = now;
    const t = reduce ? 0 : clock.getElapsedTime();
    const dim = 1;
    const ratio = renderer.getPixelRatio();
    const pulse = 0.86 + 0.14 * Math.sin((recall ? performance.now() - recall.started : 0) / 240);
    gasMats.forEach((material) => {
      material.uniforms.uDim.value = dim;
      material.uniforms.uPixelRatio.value = ratio;
    });
    expertClouds.forEach((group) => {
      if (!reduce) group.rotation.y = (group.userData.spin || 0) + t * 0.045;
      let boost = 1;
      if (recall) boost = group.userData.expertName === recall.expertName ? 1.78 : 0.52;
      else if (group.userData.fresh) boost = reduce ? 1.1 : 0.9 + 0.22 * (0.5 + 0.5 * Math.sin(t * 1.15 + (group.userData.spin || 0)));
      if (group.userData.material) group.userData.material.uniforms.uBoost.value = boost;
    });
    if (starPoints) {
      const flareAttr = starPoints.geometry.getAttribute("aFlare");
      const brightAttr = starPoints.geometry.getAttribute("aBright");
      const baseBright = starPoints.geometry.userData.baseBright || [];
      starIds.forEach((id, index) => {
        const on = Boolean(recall && recall.nodeIds.has(id));
        if (on) {
          flareAttr.setX(index, 2.25 * pulse);
          brightAttr.setX(index, 1);
        } else if (recall) {
          flareAttr.setX(index, 0.58);
          brightAttr.setX(index, (baseBright[index] || 0.5) * 0.4);
        } else {
          flareAttr.setX(index, 1);
          brightAttr.setX(index, baseBright[index] || 0.7);
        }
      });
      flareAttr.needsUpdate = true;
      brightAttr.needsUpdate = true;
      starPoints.material.uniforms.uPixelRatio.value = ratio;
    }
    if (sparkPoints) {
      const attr = sparkPoints.geometry.getAttribute("position");
      const groups = sparkPoints.userData.groups || [];
      groups.forEach((group, groupIndex) => {
        const origin = group.position;
        const radius = Math.max(3.2, (group.userData.radius || 8) * 0.42);
        for (let i = 0; i < 8; i += 1) {
          const ang = t * 0.45 + groupIndex + i * (Math.PI * 2 / 8);
          const wobble = 0.86 + 0.14 * Math.sin(t * 1.4 + i);
          attr.setXYZ(
            groupIndex * 8 + i,
            origin.x + Math.cos(ang) * radius * wobble,
            origin.y + Math.sin(ang) * radius * 0.6 * wobble,
            origin.z,
          );
        }
      });
      attr.needsUpdate = true;
      sparkPoints.material.uniforms.uPixelRatio.value = ratio;
    }
    overlay.children.forEach((child) => {
      if (child.material && child.material.uniforms && child.material.uniforms.uPixelRatio) {
        child.material.uniforms.uPixelRatio.value = ratio;
      }
    });
    filaments.forEach((filament) => {
      const hot = Boolean(filament.hot);
      if (filament.material && filament.material.uniforms.uGain) {
        filament.material.uniforms.uGain.value = hot ? 0.62 : (recall ? 0.06 : (filament.role === "source" ? 0.14 : 0.1));
      }
      const speed = hot ? 0.16 : 0.045;
      filament.beads.forEach((mote) => {
        const phase = (((reduce ? 0 : t) * speed + mote.userData.phase) % 1 + 1) % 1;
        const index = Math.min(filament.points.length - 1, Math.floor(phase * (filament.points.length - 1)));
        mote.position.copy(filament.points[index]);
        mote.material.opacity = hot ? 0.85 : 0.28;
        mote.scale.setScalar(hot ? 0.55 : 0.2);
      });
    });
    look.lerp(lookTarget, reduce ? 1 : 0.08);
    camera.position.lerp(camTarget, reduce ? 1 : 0.08);
    camera.lookAt(look);
    placeLabels();
    renderer.setRenderTarget(sceneTarget);
    renderer.setClearColor(0x000000, 0);
    renderer.clear();
    renderer.render(scene, camera);
    renderer.setRenderTarget(null);
    renderer.clear();
    renderer.render(bloomScene, bloomCamera);
    renderer.autoClear = false;
    renderer.render(overlay, camera);
    renderer.autoClear = true;
  }

  resize();
  frame();
  return {
    setData,
    resize,
    refreshLabels,
    highlight,
    screenPoint: project,
    focus(name) {
      const group = expertMeshes.get(name);
      if (group) flyTo(group);
    },
    setMode(next) {
      const paused = next === "dim" || next === "paused";
      mode = "full";
      if (paused) {
        frame(performance.now());
        mode = "dim";
        looping = false;
        return;
      }
      if (running && !looping) {
        looping = true;
        requestAnimationFrame(frame);
      }
    },
    dispose() {
      running = false;
      clearWorld();
      if (labelLayer) labelLayer.remove();
      labelLayer = null;
      sprite.dispose();
      bead.dispose();
      bloomMaterial.dispose();
      sceneTarget.dispose();
      renderer.dispose();
    },
  };
}

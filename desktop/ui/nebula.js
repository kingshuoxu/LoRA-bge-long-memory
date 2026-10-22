import * as THREE from "./vendor/three.module.js";

const PALETTES = [
  { core: [0.90, 0.20, 0.14], mid: [0.58, 0.09, 0.08], edge: [0.30, 0.05, 0.05] },
  { core: [0.10, 0.74, 0.66], mid: [0.05, 0.44, 0.42], edge: [0.03, 0.20, 0.22] },
  { core: [0.92, 0.58, 0.14], mid: [0.58, 0.32, 0.06], edge: [0.26, 0.12, 0.03] },
  { core: [0.46, 0.16, 0.90], mid: [0.26, 0.07, 0.55], edge: [0.11, 0.04, 0.26] },
  { core: [0.84, 0.26, 0.36], mid: [0.52, 0.11, 0.18], edge: [0.24, 0.05, 0.09] },
  { core: [0.20, 0.38, 0.90], mid: [0.09, 0.18, 0.55], edge: [0.04, 0.07, 0.24] },
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
  void main() {
    vColor = aColor;
    vAlpha = aAlpha * uDim;
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = clamp(aSize * uPixelRatio, 2.0, 60.0);
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

function starTexture() {
  return makeTexture((ctx, size) => {
    const mid = size / 2;
    const glow = ctx.createRadialGradient(mid, mid, 0, mid, mid, mid * 0.16);
    glow.addColorStop(0, "rgba(255,252,248,1)");
    glow.addColorStop(0.42, "rgba(255,246,230,0.75)");
    glow.addColorStop(1, "rgba(255,236,210,0)");
    ctx.fillStyle = glow;
    ctx.beginPath();
    ctx.arc(mid, mid, mid * 0.16, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = "rgba(255,250,244,0.85)";
    ctx.lineWidth = 1.15;
    ctx.beginPath();
    ctx.moveTo(mid, mid * 0.28);
    ctx.lineTo(mid, size - mid * 0.28);
    ctx.moveTo(mid * 0.28, mid);
    ctx.lineTo(size - mid * 0.28, mid);
    ctx.stroke();
    ctx.strokeStyle = "rgba(255,228,190,0.22)";
    ctx.lineWidth = 0.6;
    ctx.beginPath();
    ctx.moveTo(28, 28);
    ctx.lineTo(size - 28, size - 28);
    ctx.moveTo(size - 28, 28);
    ctx.lineTo(28, size - 28);
    ctx.stroke();
  });
}

function fallbackNebula(canvas) {
  if (canvas.parentElement) canvas.parentElement.classList.add("nebula-fallback");
  return {
    setData() {},
    resize() {},
    highlight() { return { mounted: false, nodeIds: [] }; },
    screenPoint() { return null; },
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

function randn() {
  let u = 0;
  let v = 0;
  while (u === 0) u = Math.random();
  while (v === 0) v = Math.random();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(Math.PI * 2 * v);
}

function sampleCloud(index) {
  const palette = PALETTES[index % PALETTES.length];
  const seed = index * 2.7 + 1.3;
  const target = 2400;
  const positions = [];
  const colors = [];
  const sizes = [];
  const alphas = [];
  let tries = 0;
  while (positions.length / 3 < target && tries < target * 36) {
    tries += 1;
    const x = randn() * 2.55;
    const y = randn() * 1.85;
    const z = randn() * 1.25;
    const r = Math.hypot(x / 2.55, y / 1.85, z / 1.25);
    if (r > 2.15) continue;
    const n = fbm3(x * 0.46 + seed, y * 0.46 + seed * 1.6, z * 0.46 + 2.0);
    const ridge = 1 - Math.abs(fbm3(x * 0.95 + 4.2, y * 0.95 + seed, z * 0.95) * 2 - 1);
    const field = n * 0.5 + ridge * ridge * 0.72;
    const gate = Math.exp(-r * r * 0.48);
    if (Math.random() > Math.min(1, field * gate * 1.45)) continue;
    positions.push(x, y, z);
    const paint = Math.min(1, Math.max(0, (n - 0.32) / 0.4));
    const dist = Math.min(1, r / 1.7);
    const col = mix3(mix3(palette.edge, palette.mid, paint), palette.core, (1 - dist) * 0.7);
    colors.push(col[0], col[1], col[2]);
    sizes.push(14 + Math.random() * 34);
    alphas.push(0.03 + Math.random() * 0.04);
  }
  for (let i = 0; i < 180; i += 1) {
    const x = randn() * 0.42;
    const y = randn() * 0.32;
    const z = randn() * 0.24;
    positions.push(x, y, z);
    const hot = mix3(palette.core, [
      Math.min(1.35, palette.core[0] * 1.45),
      Math.min(1.15, palette.core[1] * 1.35),
      Math.min(1.15, palette.core[2] * 1.35),
    ], 0.55);
    colors.push(hot[0], hot[1], hot[2]);
    sizes.push(8 + Math.random() * 14);
    alphas.push(0.05 + Math.random() * 0.03);
  }
  return { positions, colors, sizes, alphas };
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
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.25));
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
  const world = new THREE.Group();
  scene.add(world);
  const pickables = [];
  const factMeshes = new Map();
  const expertMeshes = new Map();
  const expertClouds = new Map();
  const nodePos = new Map();
  const filaments = [];
  const motes = [];
  const gasMats = [];
  let framed = null;
  let userMoved = false;
  let recall = null;
  let mode = "full";
  let running = true;
  let frameCount = 0;

  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  let dragging = false;
  let moved = 0;
  let lastX = 0;
  let lastY = 0;

  function clearWorld() {
    while (world.children.length) {
      const child = world.children.pop();
      child.traverse((obj) => {
        if (obj.geometry) obj.geometry.dispose();
        if (obj.material && obj.material.map !== sprite) {
          if (obj.material.map) obj.material.map.dispose();
          obj.material.dispose();
        } else if (obj.material && obj.material.map === sprite) {
          obj.material.dispose();
        }
      });
    }
    pickables.length = 0;
    factMeshes.clear();
    expertMeshes.clear();
    expertClouds.clear();
    nodePos.clear();
    filaments.length = 0;
    motes.length = 0;
    gasMats.length = 0;
    recall = null;
    framed = null;
    userMoved = false;
  }

  function makeCloud(position, index, name, expert) {
    const group = new THREE.Group();
    group.position.copy(position);
    group.rotation.x = 0.35 + index * 0.22;
    group.rotation.z = index * 0.47;
    const cloud = sampleCloud(index);
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(cloud.positions, 3));
    geometry.setAttribute("aColor", new THREE.Float32BufferAttribute(cloud.colors, 3));
    geometry.setAttribute("aSize", new THREE.Float32BufferAttribute(cloud.sizes, 1));
    geometry.setAttribute("aAlpha", new THREE.Float32BufferAttribute(cloud.alphas, 1));
    const material = new THREE.ShaderMaterial({
      uniforms: {
        uPixelRatio: { value: renderer.getPixelRatio() },
        uDim: { value: 1 },
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
      new THREE.SphereGeometry(4.4, 10, 8),
      new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false, color: 0x000000 }),
    );
    pick.userData = { kind: "expert", expertName: name, expert };
    group.add(pick);
    pickables.push(pick);
    group.userData = { kind: "expert", expertName: name, expert, baseScale: 1, spin: index * 0.9 };
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

  function addFilament(a, b, color) {
    const points = bezier(a, b, 1.6 + (filaments.length % 3) * 0.7);
    const geo = ribbonGeometry(points, 0.42);
    const tint = new THREE.Color(color);
    const material = new THREE.ShaderMaterial({
      uniforms: { uColor: { value: new THREE.Vector3(tint.r, tint.g, tint.b) } },
      vertexShader: GAS_VERT,
      fragmentShader: `
        precision mediump float;
        varying vec2 vUv;
        uniform vec3 uColor;
        void main() {
          float across = smoothstep(0.0, 0.5, vUv.y) * smoothstep(1.0, 0.5, vUv.y);
          float along = smoothstep(0.0, 0.14, vUv.x) * smoothstep(1.0, 0.86, vUv.x);
          float light = across * along;
          float alpha = light * 0.14;
          gl_FragColor = vec4(uColor * alpha, alpha);
        }
      `,
      transparent: true,
      depthWrite: false,
      depthTest: false,
      side: THREE.DoubleSide,
      premultipliedAlpha: true,
      blending: THREE.NormalBlending,
    });
    const line = new THREE.Mesh(geo, material);
    line.renderOrder = 2;
    world.add(line);
    const mote = new THREE.Sprite(new THREE.SpriteMaterial({
      map: sprite,
      color: 0xfff1c9,
      transparent: true,
      opacity: 0,
      depthWrite: false,
      blending: THREE.NormalBlending,
      premultipliedAlpha: true,
    }));
    mote.scale.setScalar(0.34);
    mote.visible = false;
    world.add(mote);
    const filament = { points, mote, source: "", target: "" };
    filaments.push(filament);
    motes.push(mote);
    return filament;
  }

  function setData(data) {
    clearWorld();
    const experts = data.experts || [];
    const facts = data.facts || [];
    const conversations = data.conversations || [];
    const links = (data.links || []).slice();
    const radius = Math.max(24, experts.length * 3.1);
    experts.forEach((expert, index) => {
      const angle = (index / Math.max(1, experts.length)) * Math.PI * 2 - Math.PI / 2;
      const pos = new THREE.Vector3(
        Math.cos(angle) * radius,
        Math.sin(angle) * radius * 0.7,
        Math.sin(angle * 2 + index) * 1.4,
      );
      nodePos.set(expert.id || `expert:${expert.name}`, pos.clone());
      makeCloud(pos, index, expert.name, expert);
    });
    experts.forEach((expert, index) => {
      const next = experts[(index + 1) % experts.length];
      if (!next || next.name === expert.name) return;
      const a = nodePos.get(expert.id || `expert:${expert.name}`);
      const b = nodePos.get(next.id || `expert:${next.name}`);
      if (!a || !b) return;
      const filament = addFilament(a, b, paletteColor(index, 2));
      filament.source = expert.id || `expert:${expert.name}`;
      filament.target = next.id || `expert:${next.name}`;
    });

    const grouped = new Map();
    facts.forEach((fact) => {
      if (!grouped.has(fact.expert)) grouped.set(fact.expert, []);
      grouped.get(fact.expert).push(fact);
    });
    grouped.forEach((group, name) => {
      const origin = nodePos.get(`expert:${name}`) || new THREE.Vector3();
      const colorIndex = Math.max(0, experts.findIndex((expert) => expert.name === name));
      group.forEach((fact, index) => {
        const golden = index * 2.399963;
        const ring = 0.4 + Math.sqrt((index + 0.5) / group.length) * 2.5;
        const pos = origin.clone().add(new THREE.Vector3(
          Math.cos(golden) * ring,
          Math.sin(golden * 1.17) * ring * 0.55,
          ((index % 5) - 2) * 0.18,
        ));
        nodePos.set(fact.id, pos.clone());
        const material = new THREE.SpriteMaterial({
          map: sprite,
          color: fact.superseded ? 0x8d97a8 : 0xfff4e4,
          transparent: true,
          opacity: fact.superseded ? 0.22 : 0.95,
          depthWrite: false,
          blending: THREE.NormalBlending,
          premultipliedAlpha: true,
        });
        const star = new THREE.Sprite(material);
        const scale = fact.superseded ? 0.28 : 0.46 + (index % 4) * 0.12;
        star.scale.setScalar(scale);
        star.position.copy(pos);
        star.userData = { kind: "fact", fact, baseScale: scale, baseOpacity: material.opacity };
        star.renderOrder = 4;
        world.add(star);
        pickables.push(star);
        factMeshes.set(fact.id, star);
      });
    });

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
      const pos = anchor.clone().add(new THREE.Vector3(0, 1.1 + (index % 3) * 0.2, 0));
      nodePos.set(conv.id, pos.clone());
      const mesh = new THREE.Sprite(new THREE.SpriteMaterial({
        map: sprite,
        color: 0xe7e0d4,
        transparent: true,
        opacity: 0.4,
        depthWrite: false,
        blending: THREE.NormalBlending,
        premultipliedAlpha: true,
      }));
      mesh.scale.setScalar(0.22);
      mesh.position.copy(pos);
      mesh.userData = { kind: "conversation", conversation: conv };
      world.add(mesh);
      pickables.push(mesh);
    });

    links.forEach((link) => {
      if (link.kind !== "entity" && link.kind !== "semantic" && link.kind !== "supersede") return;
      const a = nodePos.get(link.source);
      const b = nodePos.get(link.target);
      if (!a || !b) return;
      const filament = addFilament(a, b, link.kind === "supersede" ? 0x8a93a3 : 0xc4a36a);
      filament.source = link.source;
      filament.target = link.target;
    });

    const box = new THREE.Box3();
    expertClouds.forEach((group) => {
      box.expandByPoint(group.position.clone().add(new THREE.Vector3(8.2, 6.2, 1.6)));
      box.expandByPoint(group.position.clone().add(new THREE.Vector3(-8.2, -6.2, -1.6)));
    });
    if (box.isEmpty()) box.setFromCenterAndSize(new THREE.Vector3(), new THREE.Vector3(10, 6, 8));
    const sphere = box.getBoundingSphere(new THREE.Sphere());
    framed = {
      center: sphere.center.clone(),
      radius: Math.max(11, sphere.radius * 0.92),
    };
    applyFrame(true);
  }

  function applyFrame(immediate) {
    if (!framed) return;
    const { center, radius } = framed;
    lookTarget.copy(center);
    const fov = camera.fov * Math.PI / 180;
    const aspect = Math.max(0.35, camera.aspect || 1);
    const distY = radius / Math.tan(fov / 2);
    const distX = radius / (Math.tan(fov / 2) * aspect);
    const dist = Math.max(distY, distX) * 0.84;
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
    const ratio = Math.min(window.devicePixelRatio || 1, mode === "dim" ? 1 : 1.25);
    renderer.setPixelRatio(ratio);
    renderer.setSize(width, height, false);
    const bufferW = Math.max(1, Math.floor(width * ratio));
    const bufferH = Math.max(1, Math.floor(height * ratio));
    sceneTarget.setSize(bufferW, bufferH);
    bloomUniforms.uTexel.value.set(2.2 / bufferW, 2.2 / bufferH);
    camera.aspect = width / Math.max(1, height);
    camera.updateProjectionMatrix();
    if (!userMoved) applyFrame(true);
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
    factMeshes.forEach((mesh) => {
      mesh.scale.setScalar(mesh.userData.baseScale);
      mesh.material.opacity = mesh.userData.baseOpacity;
    });
    expertClouds.forEach((group) => group.scale.setScalar(1));
    motes.forEach((mote) => {
      mote.visible = false;
      mote.material.opacity = 0;
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

  canvas.addEventListener("pointerdown", (event) => {
    dragging = true;
    moved = 0;
    lastX = event.clientX;
    lastY = event.clientY;
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointermove", (event) => {
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
  canvas.addEventListener("pointerup", (event) => {
    dragging = false;
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
    offset.setLength(Math.min(90, Math.max(8, next)));
    camTarget.copy(look).add(offset);
  }, { passive: false });

  const clock = new THREE.Clock();
  function frame() {
    if (!running) return;
    requestAnimationFrame(frame);
    if (!canvas.clientWidth || document.hidden) return;
    frameCount += 1;
    if (mode === "dim" && frameCount % 3 !== 0) return;
    const t = reduce ? 0 : clock.getElapsedTime();
    const dim = mode === "dim" ? 0.45 : 1;
    const ratio = renderer.getPixelRatio();
    gasMats.forEach((material) => {
      material.uniforms.uDim.value = dim;
      material.uniforms.uPixelRatio.value = ratio;
    });
    expertClouds.forEach((group) => {
      if (reduce) return;
      group.rotation.y = (group.userData.spin || 0) + t * 0.05;
    });
    if (recall && !reduce) {
      const pulse = 0.55 + 0.45 * Math.sin((performance.now() - recall.started) / 160);
      factMeshes.forEach((mesh, id) => {
        const on = recall.nodeIds.has(id);
        mesh.scale.setScalar(mesh.userData.baseScale * (on ? 1.2 + pulse * 0.7 : 0.7));
        mesh.material.opacity = on ? 1 : 0.2;
      });
      const cloud = expertClouds.get(recall.expertName);
      if (cloud) cloud.scale.setScalar(1.04 + pulse * 0.04);
      const travel = ((performance.now() - recall.started) / 1400) % 1;
      filaments.forEach((filament) => {
        const hit = recall.nodeIds.has(filament.target) || recall.nodeIds.has(filament.source)
          || filament.target === `expert:${recall.expertName}` || filament.source === `expert:${recall.expertName}`;
        if (!hit || !filament.mote || !filament.points.length) return;
        const index = Math.min(filament.points.length - 1, Math.floor(travel * (filament.points.length - 1)));
        filament.mote.visible = true;
        filament.mote.position.copy(filament.points[index]);
        filament.mote.material.opacity = 0.9;
        filament.mote.scale.setScalar(0.28 + pulse * 0.12);
      });
    }
    look.lerp(lookTarget, reduce ? 1 : 0.08);
    camera.position.lerp(camTarget, reduce ? 1 : 0.08);
    camera.lookAt(look);
    renderer.setRenderTarget(sceneTarget);
    renderer.setClearColor(0x000000, 0);
    renderer.clear();
    renderer.render(scene, camera);
    renderer.setRenderTarget(null);
    renderer.clear();
    renderer.render(bloomScene, bloomCamera);
  }

  resize();
  frame();
  return {
    setData,
    resize,
    highlight,
    screenPoint: project,
    setMode(next) {
      mode = next === "dim" ? "dim" : "full";
      resize();
    },
    dispose() {
      running = false;
      clearWorld();
      sprite.dispose();
      bloomMaterial.dispose();
      sceneTarget.dispose();
      renderer.dispose();
    },
  };
}

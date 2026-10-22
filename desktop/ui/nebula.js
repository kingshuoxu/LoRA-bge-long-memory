import * as THREE from "./vendor/three.module.js";

const PALETTES = [
  { core: [0.86, 0.34, 0.32], edge: [0.55, 0.18, 0.18], dust: [0.68, 0.30, 0.24] },
  { core: [0.38, 0.70, 0.66], edge: [0.16, 0.40, 0.40], dust: [0.26, 0.52, 0.50] },
  { core: [0.82, 0.62, 0.32], edge: [0.48, 0.32, 0.14], dust: [0.62, 0.46, 0.22] },
  { core: [0.58, 0.40, 0.70], edge: [0.30, 0.18, 0.42], dust: [0.42, 0.28, 0.54] },
  { core: [0.72, 0.36, 0.42], edge: [0.42, 0.18, 0.24], dust: [0.56, 0.28, 0.32] },
  { core: [0.42, 0.56, 0.74], edge: [0.18, 0.28, 0.46], dust: [0.30, 0.42, 0.58] },
];

const GAS_VERT = `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

const GAS_FRAG = `
  precision mediump float;
  varying vec2 vUv;
  uniform vec3 uCore;
  uniform vec3 uEdge;
  uniform vec3 uDust;
  uniform float uTime;
  uniform float uSeed;
  uniform float uAlpha;

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
    for (int i = 0; i < 5; i++) {
      v += a * noise(p);
      p = p * 2.03 + vec2(1.7, 9.2);
      a *= 0.5;
    }
    return v;
  }

  void main() {
    vec2 p = vUv * 2.0 - 1.0;
    p.x *= 1.22;
    float r = length(p);
    float window = smoothstep(1.02, 0.02, r);
    float ang = uSeed * 0.65;
    float cs = cos(ang);
    float sn = sin(ang);
    vec2 q = vec2(cs * p.x - sn * p.y, sn * p.x + cs * p.y);
    vec2 drift = q + vec2(uTime * 0.012, -uTime * 0.006);
    float broad = fbm(drift * 1.15 + uSeed);
    float mid = fbm(drift * 2.3 + vec2(4.2, uSeed * 1.7));
    float fine = fbm(drift * 4.7 + uSeed * 0.8);
    float ridge = pow(clamp(1.0 - abs(mid - 0.5) * 2.0, 0.0, 1.0), 2.4);
    float veil = smoothstep(0.28, 0.86, broad);
    float knots = smoothstep(0.6, 0.95, broad * 0.7 + mid * 0.3);
    float density = (veil * 0.28 + ridge * veil * 0.7 + knots * 0.85) * (0.8 + 0.2 * fine);
    density *= window;
    density = clamp(density, 0.0, 1.0);
    vec3 col = mix(uEdge, uDust, smoothstep(0.05, 0.45, density));
    col = mix(col, uCore, smoothstep(0.2, 0.86, knots));
    col = mix(col, min(uCore * 1.25, vec3(1.0)), smoothstep(0.55, 1.0, knots));
    float light = clamp(density * uAlpha, 0.0, 1.0);
    float alpha = clamp(light * 0.88, 0.0, 0.74);
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
  void main() {
    vec4 center = texture2D(tScene, vUv);
    vec3 glow = vec3(0.0);
    float glowA = 0.0;
    float weights[5];
    weights[0] = 0.22;
    weights[1] = 0.18;
    weights[2] = 0.12;
    weights[3] = 0.07;
    weights[4] = 0.04;
    for (int i = 0; i < 5; i++) {
      float f = float(i);
      vec2 step = uTexel * (3.0 + f * 5.0);
      vec4 s1 = texture2D(tScene, vUv + vec2(step.x, 0.0));
      vec4 s2 = texture2D(tScene, vUv - vec2(step.x, 0.0));
      vec4 s3 = texture2D(tScene, vUv + vec2(0.0, step.y));
      vec4 s4 = texture2D(tScene, vUv - vec2(0.0, step.y));
      vec4 s5 = texture2D(tScene, vUv + step);
      vec4 s6 = texture2D(tScene, vUv - step);
      vec3 sum = s1.rgb + s2.rgb + s3.rgb + s4.rgb + s5.rgb + s6.rgb;
      float a = s1.a + s2.a + s3.a + s4.a + s5.a + s6.a;
      glow += sum * weights[i];
      glowA += a * weights[i];
    }
    vec3 rgb = center.rgb + glow * 0.12;
    float alpha = min(0.8, center.a + glowA * 0.015);
    gl_FragColor = vec4(rgb, alpha);
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
    const glow = ctx.createRadialGradient(mid, mid, 0, mid, mid, mid);
    glow.addColorStop(0, "rgba(255,248,236,1)");
    glow.addColorStop(0.06, "rgba(255,236,210,0.95)");
    glow.addColorStop(0.18, "rgba(210,196,170,0.22)");
    glow.addColorStop(1, "rgba(255,236,210,0)");
    ctx.fillStyle = glow;
    ctx.fillRect(0, 0, size, size);
    ctx.strokeStyle = "rgba(255,246,230,0.95)";
    ctx.lineWidth = 2.8;
    ctx.beginPath();
    ctx.moveTo(mid, 4);
    ctx.lineTo(mid, size - 4);
    ctx.moveTo(4, mid);
    ctx.lineTo(size - 4, mid);
    ctx.stroke();
    ctx.strokeStyle = "rgba(255,228,190,0.35)";
    ctx.lineWidth = 0.8;
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
  const rgb = slot === 0 ? row.core : slot === 1 ? row.edge : row.dust;
  return (Math.round(rgb[0] * 255) << 16) | (Math.round(rgb[1] * 255) << 8) | Math.round(rgb[2] * 255);
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
  if (THREE.SRGBColorSpace) renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.NoToneMapping;

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(34, 1, 0.1, 400);
  const look = new THREE.Vector3();
  const lookTarget = new THREE.Vector3();
  const camTarget = new THREE.Vector3(0, 0, 32);
  camera.position.copy(camTarget);

  const sceneTarget = new THREE.WebGLRenderTarget(8, 8, {
    format: THREE.RGBAFormat,
    type: THREE.UnsignedByteType,
    depthBuffer: false,
    stencilBuffer: false,
  });
  const bloomUniforms = {
    tScene: { value: sceneTarget.texture },
    uTexel: { value: new THREE.Vector2(1 / 8, 1 / 8) },
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

  function gasMaterial(index, seed, alpha) {
    const palette = PALETTES[index % PALETTES.length];
    const material = new THREE.ShaderMaterial({
      uniforms: {
        uCore: { value: new THREE.Vector3(...palette.core) },
        uEdge: { value: new THREE.Vector3(...palette.edge) },
        uDust: { value: new THREE.Vector3(...palette.dust) },
        uTime: { value: 0 },
        uSeed: { value: seed },
        uAlpha: { value: alpha },
      },
      vertexShader: GAS_VERT,
      fragmentShader: GAS_FRAG,
      transparent: true,
      depthWrite: false,
      depthTest: false,
      side: THREE.DoubleSide,
      premultipliedAlpha: true,
      blending: THREE.NormalBlending,
    });
    gasMats.push(material);
    return material;
  }

  function makeCloud(position, index, name, expert) {
    const group = new THREE.Group();
    group.position.copy(position);
    const layers = [
      { w: 15.2, h: 10.4, x: 0, y: 0.3, z: 0, rot: 0.2 + index * 0.25, seed: index * 2.7, alpha: 0.88 },
      { w: 11.4, h: 8.6, x: 2.2, y: 1.1, z: 0.35, rot: -0.6, seed: index * 2.7 + 1.8, alpha: 0.55 },
      { w: 9.6, h: 12.2, x: -2.4, y: -0.8, z: -0.25, rot: 0.9, seed: index * 2.7 + 3.4, alpha: 0.42 },
    ];
    layers.forEach((layer, layerIndex) => {
      const mesh = new THREE.Mesh(new THREE.PlaneGeometry(layer.w, layer.h), gasMaterial(index, layer.seed, layer.alpha));
      mesh.position.set(layer.x, layer.y, layer.z);
      mesh.rotation.z = layer.rot;
      mesh.userData = {
        kind: "expert",
        expertName: name,
        expert,
        baseOpacity: layer.alpha,
        phase: index + layerIndex,
      };
      mesh.renderOrder = 1;
      group.add(mesh);
      if (layerIndex === 0) pickables.push(mesh);
    });
    group.userData = { kind: "expert", expertName: name, expert, baseScale: 1 };
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
          float alpha = light * 0.1;
          gl_FragColor = vec4(uColor * light * 1.15, alpha);
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
      blending: THREE.AdditiveBlending,
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
          blending: THREE.AdditiveBlending,
          premultipliedAlpha: true,
        });
        const star = new THREE.Sprite(material);
        const scale = fact.superseded ? 0.7 : (2.6 + (index % 4) * 0.85) * (index % 6 === 0 ? 1.35 : 1);
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
        blending: THREE.AdditiveBlending,
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
    gasMats.forEach((material) => {
      material.uniforms.uTime.value = t;
    });
    expertClouds.forEach((group) => {
      group.children.forEach((blob) => {
        if (!blob.userData || blob.userData.phase == null || !blob.material.uniforms) return;
        blob.material.uniforms.uAlpha.value = blob.userData.baseOpacity * dim;
      });
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

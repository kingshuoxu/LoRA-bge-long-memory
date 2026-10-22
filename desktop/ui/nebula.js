import * as THREE from "./vendor/three.module.js";
import { EffectComposer } from "./vendor/postprocessing/EffectComposer.js";
import { RenderPass } from "./vendor/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "./vendor/postprocessing/UnrealBloomPass.js";

const PALETTE = [0x9ecbff, 0xf0c36a, 0x5ee0d0, 0xd7b0ff, 0xffb089, 0xb7e38a];

function colorOf(index) {
  return PALETTE[index % PALETTE.length];
}

function starTexture() {
  const size = 128;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  const mid = size / 2;
  const glow = ctx.createRadialGradient(mid, mid, 0, mid, mid, mid);
  glow.addColorStop(0, "rgba(255,255,255,1)");
  glow.addColorStop(0.08, "rgba(255,244,220,0.95)");
  glow.addColorStop(0.22, "rgba(180,210,255,0.35)");
  glow.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, size, size);
  ctx.strokeStyle = "rgba(255,248,230,0.9)";
  ctx.lineWidth = 1.2;
  ctx.beginPath();
  ctx.moveTo(mid, 6);
  ctx.lineTo(mid, size - 6);
  ctx.moveTo(6, mid);
  ctx.lineTo(size - 6, mid);
  ctx.stroke();
  ctx.strokeStyle = "rgba(255,236,190,0.35)";
  ctx.lineWidth = 0.6;
  ctx.beginPath();
  ctx.moveTo(18, 18);
  ctx.lineTo(size - 18, size - 18);
  ctx.moveTo(size - 18, 18);
  ctx.lineTo(18, size - 18);
  ctx.stroke();
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

const CLOUD_VERT = `
  varying vec3 vPos;
  varying vec3 vNormal;
  void main() {
    vPos = position;
    vNormal = normalize(normalMatrix * normal);
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;
const CLOUD_FRAG = `
  varying vec3 vPos;
  varying vec3 vNormal;
  uniform vec3 uColor;
  uniform float uTime;
  uniform float uDim;
  float hash(vec3 p) {
    return fract(sin(dot(p, vec3(127.1, 311.7, 74.7))) * 43758.5453);
  }
  float noise(vec3 p) {
    vec3 i = floor(p);
    vec3 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    float n = mix(mix(mix(hash(i), hash(i + vec3(1,0,0)), f.x),
                       mix(hash(i + vec3(0,1,0)), hash(i + vec3(1,1,0)), f.x), f.y),
                   mix(mix(hash(i + vec3(0,0,1)), hash(i + vec3(1,0,1)), f.x),
                       mix(hash(i + vec3(0,1,1)), hash(i + vec3(1,1,1)), f.x), f.y), f.z);
    return n;
  }
  float fbm(vec3 p) {
    float v = 0.0;
    float a = 0.5;
    for (int i = 0; i < 4; i++) {
      v += a * noise(p);
      p = p * 2.03 + vec3(1.7, 9.2, 3.1);
      a *= 0.5;
    }
    return v;
  }
  void main() {
    float t = uTime * (uDim > 0.5 ? 0.25 : 1.0);
    float n = fbm(normalize(vPos) * 2.4 + vec3(t * 0.05, t * 0.02, 0.0));
    float rim = pow(1.0 - abs(dot(normalize(vNormal), vec3(0.0, 0.0, 1.0))), 1.6);
    float alpha = smoothstep(0.28, 0.82, n) * 0.62 + rim * 0.18;
    vec3 col = uColor * (0.55 + n) + vec3(0.25, 0.18, 0.05) * rim;
    gl_FragColor = vec4(col, alpha);
  }
`;

export function createNebula(canvas, hooks) {
  const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: true,
    alpha: false,
    powerPreference: "high-performance",
  });
  renderer.setClearColor(0x070910, 1);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.25));
  if (THREE.SRGBColorSpace) renderer.outputColorSpace = THREE.SRGBColorSpace;
  const scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(0x070910, 0.02);
  const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 240);
  const look = new THREE.Vector3(0, 0, 0);
  const lookTarget = new THREE.Vector3(0, 0, 0);
  const camTarget = new THREE.Vector3(0, 5.5, 22);
  camera.position.copy(camTarget);

  const sprite = starTexture();
  const dust = new THREE.Group();
  const dustCount = 700;
  const dustGeo = new THREE.BufferGeometry();
  const dustPos = new Float32Array(dustCount * 3);
  for (let i = 0; i < dustCount; i += 1) {
    dustPos[i * 3] = (Math.random() - 0.5) * 90;
    dustPos[i * 3 + 1] = (Math.random() - 0.5) * 46;
    dustPos[i * 3 + 2] = (Math.random() - 0.5) * 90;
  }
  dustGeo.setAttribute("position", new THREE.BufferAttribute(dustPos, 3));
  dust.add(new THREE.Points(dustGeo, new THREE.PointsMaterial({
    color: 0xd5e4ff, size: 0.045, transparent: true, opacity: 0.75, depthWrite: false,
  })));
  scene.add(dust);

  const world = new THREE.Group();
  scene.add(world);
  const pickables = [];
  const factMeshes = new Map();
  const expertMeshes = new Map();
  const expertClouds = new Map();
  const nodePos = new Map();
  let filaments = [];
  const motes = [];
  let recall = null;
  let mode = "full";
  let bloom = null;
  let composer = null;
  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  let dragging = false;
  let moved = 0;
  let lastX = 0;
  let lastY = 0;
  let running = true;
  let frameCount = 0;

  try {
    composer = new EffectComposer(renderer);
    composer.addPass(new RenderPass(scene, camera));
    bloom = new UnrealBloomPass(new THREE.Vector2(canvas.clientWidth || 800, canvas.clientHeight || 600), 0.72, 0.38, 0.2);
    composer.addPass(bloom);
  } catch (error) {
    composer = null;
    bloom = null;
  }

  function clearWorld() {
    while (world.children.length) {
      const child = world.children.pop();
      child.traverse((obj) => {
        if (obj.geometry) obj.geometry.dispose();
        if (obj.material && obj.material !== sprite) {
          const materials = Array.isArray(obj.material) ? obj.material : [obj.material];
          materials.forEach((material) => {
            if (material.map && material.map !== sprite) material.map.dispose();
            material.dispose();
          });
        }
      });
    }
    pickables.length = 0;
    factMeshes.clear();
    expertMeshes.clear();
    expertClouds.clear();
    nodePos.clear();
    filaments = [];
    motes.forEach((mote) => {
      if (mote.material) mote.material.dispose();
    });
    motes.length = 0;
    recall = null;
  }

  function makeCloud(position, color, name) {
    const mesh = new THREE.Mesh(
      new THREE.SphereGeometry(1.55, 48, 32),
      new THREE.ShaderMaterial({
        uniforms: {
          uColor: { value: new THREE.Color(color) },
          uTime: { value: 0 },
          uDim: { value: 0 },
        },
        vertexShader: CLOUD_VERT,
        fragmentShader: CLOUD_FRAG,
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      }),
    );
    mesh.position.copy(position);
    mesh.userData = { kind: "expert", expertName: name, baseScale: 1 };
    world.add(mesh);
    expertClouds.set(name, mesh);
    return mesh;
  }

  function setData(data) {
    clearWorld();
    const experts = data.experts || [];
    const facts = data.facts || [];
    const conversations = data.conversations || [];
    const links = (data.links || []).slice();
    const expertPos = new Map();
    const radius = 7.2 + experts.length * 0.7;
    experts.forEach((expert, index) => {
      const angle = (index / Math.max(1, experts.length)) * Math.PI * 2 - Math.PI / 2;
      const pos = new THREE.Vector3(Math.cos(angle) * radius, Math.sin(index * 0.7) * 0.55, Math.sin(angle) * radius);
      expertPos.set(expert.name, pos);
      nodePos.set(expert.id || `expert:${expert.name}`, pos.clone());
      const color = colorOf(index);
      const cloud = makeCloud(pos, color, expert.name);
      cloud.userData.expert = expert;
      pickables.push(cloud);
      expertMeshes.set(expert.name, cloud);
    });

    const grouped = new Map();
    facts.forEach((fact) => {
      if (!grouped.has(fact.expert)) grouped.set(fact.expert, []);
      grouped.get(fact.expert).push(fact);
    });
    grouped.forEach((group, name) => {
      const origin = expertPos.get(name) || new THREE.Vector3();
      const colorIndex = Math.max(0, experts.findIndex((expert) => expert.name === name));
      group.forEach((fact, index) => {
        const angle = (index / group.length) * Math.PI * 2;
        const ring = 1.7 + (index % 3) * 0.42;
        const pos = origin.clone().add(new THREE.Vector3(
          Math.cos(angle) * ring,
          Math.sin(angle * 1.6) * 0.42,
          Math.sin(angle) * ring,
        ));
        nodePos.set(fact.id, pos.clone());
        const material = new THREE.SpriteMaterial({
          map: sprite,
          color: fact.superseded ? 0x66758c : colorOf(colorIndex),
          transparent: true,
          opacity: fact.superseded ? 0.28 : 0.95,
          depthWrite: false,
          blending: THREE.AdditiveBlending,
        });
        const star = new THREE.Sprite(material);
        const scale = fact.superseded ? 0.28 : 0.62;
        star.scale.setScalar(scale);
        star.position.copy(pos);
        star.userData = { kind: "fact", fact, baseScale: scale };
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
      if (count) anchor.multiplyScalar(1 / count);
      const outward = anchor.clone().normalize().multiplyScalar(3.4 + (index % 4) * 0.25);
      const pos = (count ? anchor : new THREE.Vector3()).add(outward);
      pos.y += 1.15;
      nodePos.set(conv.id, pos.clone());
      const mesh = new THREE.Mesh(
        new THREE.OctahedronGeometry(0.12, 0),
        new THREE.MeshBasicMaterial({ color: 0xd5deee, transparent: true, opacity: 0.8 }),
      );
      mesh.position.copy(pos);
      mesh.userData = { kind: "conversation", conversation: conv };
      world.add(mesh);
      pickables.push(mesh);
    });

    facts.forEach((fact) => {
      if (!fact.superseded || !fact.superseded_by) return;
      const next = facts.find((item) => item.fact_id === fact.superseded_by);
      if (next) links.push({ source: fact.id, target: next.id, kind: "supersede" });
    });

    const linePos = [];
    const lineCol = [];
    links.forEach((link) => {
      const a = nodePos.get(link.source);
      const b = nodePos.get(link.target);
      if (!a || !b) return;
      linePos.push(a.x, a.y, a.z, b.x, b.y, b.z);
      const color = new THREE.Color(
        link.kind === "source" ? 0x3ddecb
          : link.kind === "semantic" || link.kind === "entity" ? 0xf0c36a
            : link.kind === "supersede" ? 0x66758c
              : 0x8ecbff,
      );
      lineCol.push(color.r, color.g, color.b, color.r, color.g, color.b);
      filaments.push({ a: a.clone(), b: b.clone(), source: link.source, target: link.target, kind: link.kind });
    });
    if (linePos.length) {
      const geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.Float32BufferAttribute(linePos, 3));
      geo.setAttribute("color", new THREE.Float32BufferAttribute(lineCol, 3));
      world.add(new THREE.LineSegments(geo, new THREE.LineBasicMaterial({
        vertexColors: true, transparent: true, opacity: 0.28, blending: THREE.AdditiveBlending, depthWrite: false,
      })));
    }
    filaments.forEach((filament) => {
      const mote = new THREE.Sprite(new THREE.SpriteMaterial({
        map: sprite, color: 0xfff1c9, transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending,
      }));
      mote.scale.setScalar(0.22);
      mote.visible = false;
      world.add(mote);
      motes.push(mote);
      filament.mote = mote;
    });
  }

  function resize() {
    const width = canvas.clientWidth || 800;
    const height = canvas.clientHeight || 600;
    const ratio = Math.min(window.devicePixelRatio || 1, mode === "dim" ? 1 : 1.25);
    renderer.setPixelRatio(ratio);
    renderer.setSize(width, height, false);
    if (composer) composer.setSize(width, height);
    if (bloom) bloom.setSize(width, height);
    camera.aspect = width / Math.max(1, height);
    camera.updateProjectionMatrix();
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
      mesh.material.opacity = mesh.userData.fact && mesh.userData.fact.superseded ? 0.28 : 0.95;
    });
    expertClouds.forEach((mesh) => mesh.scale.setScalar(1));
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
    const pos = object.getWorldPosition(new THREE.Vector3());
    lookTarget.copy(pos);
    const offset = camera.position.clone().sub(look);
    if (offset.length() < 0.1) offset.set(0, 2, 8);
    offset.setLength(Math.min(14, Math.max(6.5, offset.length() * 0.72)));
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
      const offset = camTarget.clone().sub(look);
      const spherical = new THREE.Spherical().setFromVector3(offset);
      spherical.theta -= dx * 0.005;
      spherical.phi = Math.min(Math.PI - 0.2, Math.max(0.2, spherical.phi + dy * 0.005));
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
    const offset = camTarget.clone().sub(look);
    const next = offset.length() * (event.deltaY > 0 ? 1.08 : 0.92);
    offset.setLength(Math.min(64, Math.max(5.5, next)));
    camTarget.copy(look).add(offset);
  }, { passive: false });

  const clock = new THREE.Clock();
  function renderScene() {
    if (composer) {
      try {
        composer.render();
        return;
      } catch (error) {
        composer = null;
      }
    }
    renderer.render(scene, camera);
  }

  function frame() {
    if (!running) return;
    requestAnimationFrame(frame);
    if (!canvas.clientWidth || document.hidden) return;
    frameCount += 1;
    if (mode === "dim" && frameCount % 3 !== 0) return;
    const t = reduce ? 1.2 : clock.getElapsedTime();
    if (!reduce && mode !== "dim") dust.rotation.y = t * 0.008;
    expertClouds.forEach((mesh) => {
      if (mesh.material.uniforms) {
        mesh.material.uniforms.uTime.value = t;
        mesh.material.uniforms.uDim.value = mode === "dim" ? 1 : 0;
      }
      if (!reduce) mesh.rotation.y = t * 0.05;
    });
    if (recall && !reduce) {
      const pulse = 0.55 + 0.45 * Math.sin((performance.now() - recall.started) / 160);
      factMeshes.forEach((mesh, id) => {
        const on = recall.nodeIds.has(id);
        mesh.scale.setScalar(mesh.userData.baseScale * (on ? 1.15 + pulse * 0.85 : 0.72));
        mesh.material.opacity = on ? 1 : 0.22;
      });
      const cloud = expertClouds.get(recall.expertName);
      if (cloud) cloud.scale.setScalar(1.04 + pulse * 0.08);
      const travel = ((performance.now() - recall.started) / 1400) % 1;
      filaments.forEach((filament) => {
        const hit = recall.nodeIds.has(filament.target) || recall.nodeIds.has(filament.source)
          || filament.target === `expert:${recall.expertName}` || filament.source === `expert:${recall.expertName}`;
        if (!hit || !filament.mote) return;
        filament.mote.visible = true;
        filament.mote.position.lerpVectors(filament.a, filament.b, travel);
        filament.mote.material.opacity = 0.85;
        filament.mote.scale.setScalar(0.18 + pulse * 0.12);
      });
    }
    look.lerp(lookTarget, reduce ? 1 : 0.08);
    camera.position.lerp(camTarget, reduce ? 1 : 0.08);
    camera.lookAt(look);
    renderScene();
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
      if (bloom) bloom.strength = mode === "dim" ? 0.16 : 0.72;
      resize();
    },
    dispose() {
      running = false;
      clearWorld();
      sprite.dispose();
      renderer.dispose();
    },
  };
}

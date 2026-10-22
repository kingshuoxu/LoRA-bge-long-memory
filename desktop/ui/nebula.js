import * as THREE from "./vendor/three.module.js";

const TONES = [
  [0xd7b4ff, 0x6ee0d0, 0xf0c36a],
  [0x9ecbff, 0xc9a6ff, 0xf2d291],
  [0x7fd6c8, 0xe7c27a, 0xb9a0ff],
  [0xf0b089, 0x8fd0ff, 0xd7b0ff],
  [0xc6e38a, 0xf0c36a, 0x7ec8ff],
  [0xe7b0ff, 0x5ee0d0, 0xf6d48a],
];

function tone(index, slot) {
  const row = TONES[index % TONES.length];
  return row[slot % row.length];
}

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

function puffTexture(rgb) {
  return makeTexture((ctx, size) => {
    const [r, g, b] = rgb;
    const blobs = [
      [0.50, 0.48, 0.46, 0.92],
      [0.34, 0.42, 0.32, 0.7],
      [0.66, 0.40, 0.3, 0.62],
      [0.46, 0.66, 0.34, 0.55],
      [0.58, 0.34, 0.24, 0.48],
    ];
    blobs.forEach(([x, y, radius, alpha]) => {
      const glow = ctx.createRadialGradient(x * size, y * size, 0, x * size, y * size, radius * size);
      glow.addColorStop(0, `rgba(${r},${g},${b},${alpha})`);
      glow.addColorStop(0.22, `rgba(${r},${g},${b},${(alpha * 0.9).toFixed(3)})`);
      glow.addColorStop(0.55, `rgba(${r},${g},${b},${(alpha * 0.45).toFixed(3)})`);
      glow.addColorStop(1, `rgba(${r},${g},${b},0)`);
      ctx.fillStyle = glow;
      ctx.fillRect(0, 0, size, size);
    });
  });
}

function starTexture() {
  return makeTexture((ctx, size) => {
    const mid = size / 2;
    const glow = ctx.createRadialGradient(mid, mid, 0, mid, mid, mid);
    glow.addColorStop(0, "rgba(255,255,255,1)");
    glow.addColorStop(0.08, "rgba(255,244,220,0.9)");
    glow.addColorStop(0.2, "rgba(190,214,255,0.28)");
    glow.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = glow;
    ctx.fillRect(0, 0, size, size);
    ctx.strokeStyle = "rgba(255,248,230,0.85)";
    ctx.lineWidth = 1.1;
    ctx.beginPath();
    ctx.moveTo(mid, 8);
    ctx.lineTo(mid, size - 8);
    ctx.moveTo(8, mid);
    ctx.lineTo(size - 8, mid);
    ctx.stroke();
    ctx.strokeStyle = "rgba(255,236,190,0.28)";
    ctx.lineWidth = 0.6;
    ctx.beginPath();
    ctx.moveTo(22, 22);
    ctx.lineTo(size - 22, size - 22);
    ctx.moveTo(size - 22, 22);
    ctx.lineTo(22, size - 22);
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
  if (side.lengthSq() > 1e-6) side.normalize().multiplyScalar(dir.length() * 0.16);
  mid.add(side);
  mid.y += lift;
  const points = [];
  for (let i = 0; i <= 28; i += 1) {
    const t = i / 28;
    const u = 1 - t;
    points.push(a.clone().multiplyScalar(u * u).add(mid.clone().multiplyScalar(2 * u * t)).add(b.clone().multiplyScalar(t * t)));
  }
  return points;
}

export function createNebula(canvas, hooks) {
  const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha: true,
      premultipliedAlpha: false,
      powerPreference: "high-performance",
    });
  } catch (error) {
    return fallbackNebula(canvas);
  }
  if (!renderer.getContext()) return fallbackNebula(canvas);
  renderer.setClearColor(0x000000, 0);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.25));
  if (THREE.SRGBColorSpace) renderer.outputColorSpace = THREE.SRGBColorSpace;

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 400);
  const look = new THREE.Vector3();
  const lookTarget = new THREE.Vector3();
  const camTarget = new THREE.Vector3(0, 1.2, 28);
  camera.position.copy(camTarget);

  const PALETTES = [
    [[226, 156, 255], [176, 90, 240], [110, 245, 230]],
    [[72, 250, 226], [24, 186, 176], [190, 150, 255]],
    [[255, 128, 32], [230, 80, 16], [255, 220, 120]],
    [[255, 96, 156], [214, 48, 120], [150, 196, 255]],
    [[64, 156, 255], [24, 90, 230], [120, 245, 220]],
    [[196, 255, 84], [120, 210, 40], [255, 214, 96]],
  ];
  const puffs = PALETTES.map((colors) => colors.map((rgb) => puffTexture(rgb)));
  const puffMaps = new Set(puffs.flat());
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
        if (obj.material && obj.material.map && !puffMaps.has(obj.material.map) && obj.material.map !== sprite) {
          if (obj.material.map) obj.material.map.dispose();
        }
        if (obj.material) obj.material.dispose();
      });
    }
    pickables.length = 0;
    factMeshes.clear();
    expertMeshes.clear();
    expertClouds.clear();
    nodePos.clear();
    filaments.length = 0;
    motes.length = 0;
    recall = null;
    framed = null;
    userMoved = false;
  }

  function makeCloud(position, index, name, expert) {
    const group = new THREE.Group();
    group.position.copy(position);
    const maps = puffs[index % puffs.length];
    const rot = index * 0.85;
    const turn = (x, y) => ({
      x: x * Math.cos(rot) - y * Math.sin(rot),
      y: x * Math.sin(rot) + y * Math.cos(rot),
    });
    const layout = [
      [-0.2, 0.05, 0.0, 6.8, 4.0, 0.9, 0],
      [1.15, 0.4, 0.15, 3.8, 3.0, 0.98, 0],
      [-1.25, -0.3, -0.1, 3.6, 2.8, 0.97, 1],
      [0.3, -1.05, 0.2, 3.2, 2.5, 0.96, 2],
      [1.7, -0.2, 0.05, 2.6, 2.0, 0.86, 1],
      [-1.6, 0.65, 0.1, 2.5, 2.1, 0.84, 2],
      [0.2, 1.15, -0.15, 2.3, 1.8, 0.95, 0],
      [-0.4, 0.2, 0.25, 1.8, 1.5, 1, 0],
    ];
    layout.forEach(([x, y, z, sx, sy, opacity, slot], i) => {
      const spun = turn(x, y);
      const material = new THREE.SpriteMaterial({
        map: maps[slot],
        color: 0xffffff,
        transparent: true,
        opacity,
        depthWrite: false,
        depthTest: false,
        blending: THREE.NormalBlending,
      });
      const blob = new THREE.Sprite(material);
      blob.position.set(spun.x, spun.y, z);
      blob.scale.set(sx, sy, 1);
      blob.userData = {
        kind: "expert",
        expertName: name,
        expert,
        baseOpacity: opacity,
        phase: i + index * 3,
        base: blob.position.clone(),
      };
      blob.renderOrder = 1;
      group.add(blob);
      pickables.push(blob);
    });
    const knots = [layout[1], layout[2], layout[4], layout[6]];
    knots.forEach((knot, knotIndex) => {
      const spun = turn(knot[0], knot[1]);
      const points = bezier(
        new THREE.Vector3(0, 0, 0),
        new THREE.Vector3(spun.x, spun.y, knot[2]),
        0.18 + knotIndex * 0.05,
      );
      const geo = new THREE.BufferGeometry().setFromPoints(points);
      const line = new THREE.Line(geo, new THREE.LineBasicMaterial({
        color: PALETTES[index % PALETTES.length][0].reduce((hex, channel, channelIndex) => hex | (channel << (16 - channelIndex * 8)), 0),
        transparent: true,
        opacity: 0.35,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      }));
      line.renderOrder = 2;
      group.add(line);
    });
    group.userData = { kind: "expert", expertName: name, expert, baseScale: 1 };
    world.add(group);
    expertClouds.set(name, group);
    expertMeshes.set(name, group);
    return group;
  }

  function addFilament(a, b, color) {
    const points = bezier(a, b, 0.35 + (filaments.length % 3) * 0.15);
    const geo = new THREE.BufferGeometry().setFromPoints(points);
    const material = new THREE.LineBasicMaterial({
      color,
      transparent: true,
      opacity: 0.62,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    world.add(new THREE.Line(geo, material));
    const mote = new THREE.Sprite(new THREE.SpriteMaterial({
      map: sprite,
      color: 0xfff1c9,
      transparent: true,
      opacity: 0,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    }));
    mote.scale.setScalar(0.28);
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
    const radius = Math.max(9.6, experts.length * 1.45);
    experts.forEach((expert, index) => {
      const angle = (index / Math.max(1, experts.length)) * Math.PI * 2 - Math.PI / 2;
      const pos = new THREE.Vector3(
        Math.cos(angle) * radius,
        Math.sin(angle) * radius * 0.7,
        Math.sin(angle * 2 + index) * 0.85,
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
      const rgb = PALETTES[index % PALETTES.length][2];
      const filament = addFilament(a, b, (rgb[0] << 16) | (rgb[1] << 8) | rgb[2]);
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
        const ring = 0.2 + Math.sqrt((index + 0.5) / group.length) * 1.15;
        const pos = origin.clone().add(new THREE.Vector3(
          Math.cos(golden) * ring,
          Math.sin(golden * 1.3) * ring * 0.62,
          ((index % 5) - 2) * 0.12,
        ));
        nodePos.set(fact.id, pos.clone());
        const material = new THREE.SpriteMaterial({
          map: sprite,
          color: fact.superseded ? 0x66758c : tone(colorIndex, index),
          transparent: true,
          opacity: fact.superseded ? 0.28 : 0.95,
          depthWrite: false,
          blending: THREE.AdditiveBlending,
        });
        const star = new THREE.Sprite(material);
        const scale = fact.superseded ? 0.2 : 0.48 + (index % 3) * 0.08;
        star.scale.setScalar(scale);
        star.position.copy(pos);
        star.userData = { kind: "fact", fact, baseScale: scale, baseOpacity: material.opacity };
        star.renderOrder = 3;
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
      const pos = anchor.clone().add(new THREE.Vector3(0, 0.8 + (index % 3) * 0.15, 0));
      nodePos.set(conv.id, pos.clone());
      const mesh = new THREE.Sprite(new THREE.SpriteMaterial({
        map: sprite,
        color: 0xd5deee,
        transparent: true,
        opacity: 0.45,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      }));
      mesh.scale.setScalar(0.16);
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
      const filament = addFilament(a, b, link.kind === "supersede" ? 0x66758c : 0xf0c36a);
      filament.source = link.source;
      filament.target = link.target;
    });

    const box = new THREE.Box3();
    expertClouds.forEach((group) => {
      box.expandByPoint(group.position.clone().add(new THREE.Vector3(3.6, 2.6, 1.4)));
      box.expandByPoint(group.position.clone().add(new THREE.Vector3(-3.6, -2.6, -1.4)));
    });
    if (box.isEmpty()) box.setFromCenterAndSize(new THREE.Vector3(), new THREE.Vector3(8, 4, 8));
    const sphere = box.getBoundingSphere(new THREE.Sphere());
    framed = {
      center: sphere.center.clone(),
      radius: Math.max(9.5, sphere.radius * 0.96),
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
    const dist = Math.max(distY, distX) * 0.94;
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
    if (offset.length() < 0.1) offset.set(0, 1.2, 10);
    offset.setLength(Math.min(16, Math.max(7, offset.length() * 0.72)));
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
    offset.setLength(Math.min(80, Math.max(6, next)));
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
    expertClouds.forEach((group) => {
      group.children.forEach((blob) => {
        if (!blob.userData || blob.userData.phase == null) return;
        const base = blob.userData.base || blob.position.clone();
        if (!blob.userData.base) blob.userData.base = base.clone();
        if (!reduce) {
          blob.position.x = blob.userData.base.x + Math.sin(t * 0.25 + blob.userData.phase) * 0.06;
          blob.position.y = blob.userData.base.y + Math.cos(t * 0.2 + blob.userData.phase) * 0.04;
        }
        blob.material.opacity = blob.userData.baseOpacity * dim;
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
      if (cloud) cloud.scale.setScalar(1.04 + pulse * 0.05);
      const travel = ((performance.now() - recall.started) / 1400) % 1;
      filaments.forEach((filament) => {
        const hit = recall.nodeIds.has(filament.target) || recall.nodeIds.has(filament.source)
          || filament.target === `expert:${recall.expertName}` || filament.source === `expert:${recall.expertName}`;
        if (!hit || !filament.mote || !filament.points.length) return;
        const index = Math.min(filament.points.length - 1, Math.floor(travel * (filament.points.length - 1)));
        filament.mote.visible = true;
        filament.mote.position.copy(filament.points[index]);
        filament.mote.material.opacity = 0.9;
        filament.mote.scale.setScalar(0.22 + pulse * 0.1);
      });
    }
    look.lerp(lookTarget, reduce ? 1 : 0.08);
    camera.position.lerp(camTarget, reduce ? 1 : 0.08);
    camera.lookAt(look);
    renderer.render(scene, camera);
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
      puffMaps.forEach((texture) => texture.dispose());
      sprite.dispose();
      renderer.dispose();
    },
  };
}

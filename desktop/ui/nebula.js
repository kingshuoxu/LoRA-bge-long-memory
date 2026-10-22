import * as THREE from "./vendor/three.module.js";

const PALETTE = [0x8ecbff, 0xf0c36a, 0x3ddecb, 0xd7a1ff, 0xff9b7a, 0x9be58a, 0xf2a4c8, 0xb0c4ff];

function colorOf(index) {
  return PALETTE[index % PALETTE.length];
}

export function createNebula(canvas, hooks) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  const scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(0x070910, 0.028);
  const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 240);
  const look = new THREE.Vector3(0, 0, 0);
  const camTarget = new THREE.Vector3(0, 6, 24);
  camera.position.copy(camTarget);

  scene.add(new THREE.AmbientLight(0x9eb4d8, 0.7));
  const key = new THREE.PointLight(0x8ecbff, 18, 90);
  key.position.set(6, 14, 12);
  scene.add(key);
  const warm = new THREE.PointLight(0xf0c36a, 10, 70);
  warm.position.set(-12, 2, -8);
  scene.add(warm);

  const dust = new THREE.Group();
  const starGeo = new THREE.BufferGeometry();
  const starCount = 600;
  const positions = new Float32Array(starCount * 3);
  for (let i = 0; i < starCount; i += 1) {
    positions[i * 3] = (Math.random() - 0.5) * 80;
    positions[i * 3 + 1] = (Math.random() - 0.5) * 40;
    positions[i * 3 + 2] = (Math.random() - 0.5) * 80;
  }
  starGeo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  dust.add(new THREE.Points(starGeo, new THREE.PointsMaterial({
    color: 0xc9d7ee, size: 0.06, transparent: true, opacity: 0.7, depthWrite: false,
  })));
  scene.add(dust);

  const world = new THREE.Group();
  scene.add(world);

  const pickables = [];
  const factMeshes = new Map();
  const expertMeshes = new Map();
  const expertClouds = new Map();
  let recall = null;
  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  let dragging = false;
  let moved = 0;
  let lastX = 0;
  let lastY = 0;
  let running = true;

  function clearWorld() {
    while (world.children.length) {
      const child = world.children.pop();
      child.traverse((obj) => {
        if (obj.geometry) obj.geometry.dispose();
        if (obj.material) {
          if (Array.isArray(obj.material)) obj.material.forEach((item) => item.dispose());
          else obj.material.dispose();
        }
      });
    }
    pickables.length = 0;
    factMeshes.clear();
    expertMeshes.clear();
    expertClouds.clear();
    recall = null;
  }

  function addGlow(position, color, scale) {
    const geo = new THREE.SphereGeometry(1, 20, 16);
    const mat = new THREE.MeshBasicMaterial({
      color, transparent: true, opacity: 0.08, depthWrite: false,
    });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.copy(position);
    mesh.scale.setScalar(scale);
    world.add(mesh);
  }

  function setData(data) {
    clearWorld();
    const experts = data.experts || [];
    const facts = data.facts || [];
    const conversations = data.conversations || [];
    const links = data.links || [];
    const expertPos = new Map();
    const nodePos = new Map();
    const radius = 6.5 + experts.length * 0.8;
    experts.forEach((expert, index) => {
      const angle = (index / Math.max(1, experts.length)) * Math.PI * 2 - Math.PI / 2;
      const pos = new THREE.Vector3(Math.cos(angle) * radius, Math.sin(index) * 0.4, Math.sin(angle) * radius);
      expertPos.set(expert.name, pos);
      nodePos.set(expert.id || `expert:${expert.name}`, pos);
      const color = colorOf(index);
      addGlow(pos, color, 2.8);
      const cloudCount = 90;
      const cloudGeo = new THREE.BufferGeometry();
      const cloudPos = new Float32Array(cloudCount * 3);
      for (let i = 0; i < cloudCount; i += 1) {
        const theta = Math.random() * Math.PI * 2;
        const phi = Math.acos(2 * Math.random() - 1);
        const r = 1.1 + Math.random() * 1.7;
        cloudPos[i * 3] = pos.x + r * Math.sin(phi) * Math.cos(theta);
        cloudPos[i * 3 + 1] = pos.y + r * Math.cos(phi) * 0.6;
        cloudPos[i * 3 + 2] = pos.z + r * Math.sin(phi) * Math.sin(theta);
      }
      cloudGeo.setAttribute("position", new THREE.BufferAttribute(cloudPos, 3));
      const cloudMat = new THREE.PointsMaterial({
        color, size: 0.09, transparent: true, opacity: 0.75, depthWrite: false, blending: THREE.AdditiveBlending,
      });
      const cloud = new THREE.Points(cloudGeo, cloudMat);
      cloud.userData = { baseOpacity: 0.75, baseSize: 0.09 };
      expertClouds.set(expert.name, cloud);
      world.add(cloud);
      const core = new THREE.Mesh(
        new THREE.SphereGeometry(0.28, 20, 16),
        new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.8, roughness: 0.4 }),
      );
      core.position.copy(pos);
      core.userData = { kind: "expert", expert, baseEmissive: 0.8 };
      expertMeshes.set(expert.name, core);
      world.add(core);
      pickables.push(core);
    });

    const grouped = new Map();
    facts.forEach((fact) => {
      if (!grouped.has(fact.expert)) grouped.set(fact.expert, []);
      grouped.get(fact.expert).push(fact);
    });
    grouped.forEach((group, name) => {
      const origin = expertPos.get(name) || new THREE.Vector3();
      const colorIndex = experts.findIndex((expert) => expert.name === name);
      group.forEach((fact, index) => {
        const angle = (index / group.length) * Math.PI * 2;
        const ring = 1.35 + (index % 3) * 0.38;
        const pos = origin.clone().add(new THREE.Vector3(Math.cos(angle) * ring, Math.sin(angle * 1.7) * 0.45, Math.sin(angle) * ring));
        nodePos.set(fact.id, pos);
        const color = fact.superseded ? 0x66758c : colorOf(Math.max(0, colorIndex));
        const star = new THREE.Mesh(
          new THREE.SphereGeometry(fact.superseded ? 0.07 : 0.12, 16, 12),
          new THREE.MeshStandardMaterial({
            color,
            emissive: color,
            emissiveIntensity: fact.superseded ? 0.15 : 1.15,
            roughness: 0.25,
            transparent: true,
            opacity: fact.superseded ? 0.38 : 1,
          }),
        );
        star.position.copy(pos);
        star.userData = {
          kind: "fact",
          fact,
          baseEmissive: fact.superseded ? 0.15 : 1.15,
          baseOpacity: fact.superseded ? 0.38 : 1,
        };
        factMeshes.set(fact.id, star);
        world.add(star);
        pickables.push(star);
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
      const outward = anchor.clone().normalize().multiplyScalar(3.2 + (index % 4) * 0.3);
      const pos = (count ? anchor : new THREE.Vector3(0, 0, 0)).add(outward);
      pos.y += 1.1;
      nodePos.set(conv.id, pos);
      const mesh = new THREE.Mesh(
        new THREE.OctahedronGeometry(0.16, 0),
        new THREE.MeshStandardMaterial({ color: 0xd5deee, emissive: 0x8aa0c0, emissiveIntensity: 0.35, roughness: 0.35 }),
      );
      mesh.position.copy(pos);
      mesh.userData = { kind: "conversation", conversation: conv };
      world.add(mesh);
      pickables.push(mesh);
    });

    facts.forEach((fact) => {
      if (!fact.superseded || !fact.superseded_by) return;
      const next = facts.find((item) => item.fact_id === fact.superseded_by);
      if (!next) return;
      links.push({ source: fact.id, target: next.id, kind: "supersede" });
    });

    const linePos = [];
    const lineCol = [];
    links.forEach((link) => {
      const a = nodePos.get(link.source);
      const b = nodePos.get(link.target);
      if (!a || !b) return;
      linePos.push(a.x, a.y, a.z, b.x, b.y, b.z);
      let color = new THREE.Color(0x8ea2c4);
      if (link.kind === "semantic" || link.kind === "entity") color = new THREE.Color(0xf0c36a);
      if (link.kind === "source") color = new THREE.Color(0x3ddecb);
      if (link.kind === "supersede") color = new THREE.Color(0x66758c);
      if (link.kind === "member") color = new THREE.Color(0x8ecbff);
      lineCol.push(color.r, color.g, color.b, color.r, color.g, color.b);
    });
    if (linePos.length) {
      const geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.Float32BufferAttribute(linePos, 3));
      geo.setAttribute("color", new THREE.Float32BufferAttribute(lineCol, 3));
      world.add(new THREE.LineSegments(geo, new THREE.LineBasicMaterial({
        vertexColors: true, transparent: true, opacity: 0.38,
      })));
    }
  }

  function resize() {
    const width = canvas.clientWidth || 800;
    const height = canvas.clientHeight || 600;
    renderer.setSize(width, height, false);
    camera.aspect = width / Math.max(1, height);
    camera.updateProjectionMatrix();
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
      spherical.phi = Math.min(Math.PI - 0.25, Math.max(0.25, spherical.phi + dy * 0.005));
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
      if (hits.length) hooks.onSelect(hits[0].object.userData);
    }
  });
  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    const offset = camTarget.clone().sub(look);
    const next = offset.length() * (event.deltaY > 0 ? 1.08 : 0.92);
    offset.setLength(Math.min(60, Math.max(6, next)));
    camTarget.copy(look).add(offset);
  }, { passive: false });

  function restoreRecall() {
    factMeshes.forEach((mesh) => {
      mesh.material.emissiveIntensity = mesh.userData.baseEmissive;
      mesh.material.opacity = mesh.userData.baseOpacity;
      mesh.scale.setScalar(1);
    });
    expertMeshes.forEach((mesh) => {
      mesh.material.emissiveIntensity = mesh.userData.baseEmissive;
      mesh.scale.setScalar(1);
    });
    expertClouds.forEach((cloud) => {
      cloud.material.opacity = cloud.userData.baseOpacity;
      cloud.material.size = cloud.userData.baseSize;
    });
  }

  function highlight(trace) {
    recall = null;
    restoreRecall();
    const mounted = Boolean(trace && trace.mounted && trace.mounted_expert);
    if (!mounted) return { mounted: false, nodeIds: [] };
    const nodeIds = (trace.matched_facts || []).map((fact) => fact.node_id).filter((id) => factMeshes.has(id));
    recall = { expertName: trace.mounted_expert, nodeIds: new Set(nodeIds), started: performance.now() };
    return { mounted: true, nodeIds: nodeIds.length ? nodeIds : [`expert:${trace.mounted_expert}`] };
  }

  function screenPoint(nodeId) {
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

  const clock = new THREE.Clock();
  function frame() {
    if (!running) return;
    requestAnimationFrame(frame);
    const t = clock.getElapsedTime();
    dust.rotation.y = t * 0.012;
    world.rotation.y = Math.sin(t * 0.08) * 0.04;
    if (recall) {
      const pulse = 0.55 + 0.45 * Math.sin((performance.now() - recall.started) / 140);
      factMeshes.forEach((mesh, id) => {
        const on = recall.nodeIds.has(id);
        mesh.material.emissiveIntensity = on ? 1.4 + pulse * 2.4 : mesh.userData.baseEmissive * 0.25;
        mesh.material.opacity = on ? 1 : Math.min(mesh.userData.baseOpacity, 0.28);
        mesh.scale.setScalar(on ? 1 + pulse * 0.45 : 1);
      });
      expertMeshes.forEach((mesh, name) => {
        const on = name === recall.expertName;
        mesh.material.emissiveIntensity = on ? 1.2 + pulse * 1.6 : mesh.userData.baseEmissive * 0.3;
        mesh.scale.setScalar(on ? 1 + pulse * 0.22 : 1);
      });
      expertClouds.forEach((cloud, name) => {
        const on = name === recall.expertName;
        cloud.material.opacity = on ? 0.95 : 0.22;
        cloud.material.size = on ? 0.12 + pulse * 0.04 : cloud.userData.baseSize;
      });
    }
    camera.position.lerp(camTarget, 0.08);
    camera.lookAt(look);
    renderer.render(scene, camera);
  }

  resize();
  frame();
  return {
    setData,
    resize,
    highlight,
    screenPoint,
    dispose() {
      running = false;
      clearWorld();
      renderer.dispose();
    },
  };
}

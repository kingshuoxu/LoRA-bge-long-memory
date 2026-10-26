/** 星云把专家、事实、来源对话分成三层节点。事实要落在云团外面，来源再往外。 */

const SPEAKERS = new Set(["我", "我们", "咱们", "咱", "i", "me", "my", "mine", "we", "our", "ours", "us"]);

function speaker(text) {
  return SPEAKERS.has(String(text || "").trim().toLowerCase());
}

export function satelliteOffset(index, count, reach) {
  const span = Math.max(1, count);
  const ang = span === 1 ? -0.55 : (index / span) * Math.PI * 2 - 0.4;
  const dist = Number(reach) + 3.6 + Math.sqrt(index) * 1.5;
  return {
    x: Math.cos(ang) * dist,
    y: Math.sin(ang) * dist * 0.72,
    z: ((index % 5) - 2) * 0.12,
    dist,
  };
}

export function sourceOffset(fact, expert) {
  const dx = fact.x - expert.x;
  const dy = fact.y - expert.y;
  const dz = (fact.z || 0) - (expert.z || 0);
  let x = dx;
  let y = dy;
  let z = dz;
  let len = Math.hypot(x, y, z);
  if (len < 0.4) {
    x = -1;
    y = 0.3;
    z = 0;
    len = Math.hypot(x, y, z);
  }
  const push = 8.2;
  return {
    x: fact.x + (x / len) * push,
    y: fact.y + (y / len) * push,
    z: (fact.z || 0) + (z / len) * push,
  };
}

export function factCaption(fact) {
  const statement = String((fact && fact.statement) || "").replace(/[。．.!]+$/u, "").trim();
  const value = String((fact && fact.value) || "").trim();
  const attr = String((fact && fact.attr) || "").trim();
  const name = statement || value || attr;
  const meta = attr && attr !== name ? attr : (value && value !== name ? value : "");
  return { name, meta };
}

export function expertCaption(expert, facts) {
  const raw = String((expert && (expert.display_name || expert.name)) || "").trim();
  const parts = raw.replace(/等$/, "").split(/[、,]/).map((part) => part.trim()).filter(Boolean);
  if (raw && parts.length && parts.some((part) => !speaker(part))) return raw;
  const owned = (facts || []).filter((fact) => {
    if (!expert) return true;
    return fact.expert === expert.name || fact.expert === expert.id;
  });
  const values = [];
  owned.forEach((fact) => {
    const value = String(fact.value || "").trim();
    const attr = String(fact.attr || "").trim();
    const piece = value && !speaker(value) ? value : (attr && !speaker(attr) ? attr : "");
    if (piece && !values.includes(piece)) values.push(piece);
  });
  if (!values.length) return raw;
  const shown = values.slice(0, 2).join("、");
  return values.length > 2 ? `${shown}等` : shown;
}

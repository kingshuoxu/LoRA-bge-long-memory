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

function isChapter(text) {
  return /第[0-9０-９一二三四五六七八九十百零两]+[章节回部篇]/.test(String(text || ""));
}

function withoutChapter(text) {
  return String(text || "")
    .replace(/第[0-9０-９一二三四五六七八九十百零两]+[章节回部篇][\s　]*[^\s，。！？\n]{0,12}/g, "")
    .replace(/^[，,、\s]+/, "")
    .trim();
}

export function factCaption(fact) {
  const statement = withoutChapter(String((fact && fact.statement) || "").replace(/[。．.!]+$/u, ""));
  let value = String((fact && fact.value) || "").trim();
  let attr = String((fact && fact.attr) || "").trim();
  if (isChapter(value)) value = "";
  if (isChapter(attr)) attr = "";
  const named = statement.match(/名叫([\u4e00-\u9fffA-Za-z0-9·]{1,12})/);
  const year = statement.match(/[0-9]{3,4}年/);
  const measure = statement.match(/[0-9零〇一二三四五六七八九十百两]{1,8}(?:米|面)/);
  if (!value || value.length > 12 || value.includes("，") || value.includes(",")) {
    if (named) value = named[1];
    else if (measure) value = measure[0];
    else if (year) value = year[0];
    else value = statement.split(/[，,]/)[0].slice(0, 12);
  }
  const name = value || statement.slice(0, 12) || "这条事实";
  let meta = "";
  if (attr && attr !== name && attr !== "重点" && attr.length <= 12 && !isChapter(attr)) {
    meta = attr;
  } else if (statement && statement !== name) {
    meta = statement.replace(name, "").replace(/^[，,、\s名叫]+/, "").split(/[，,]/)[0].slice(0, 12);
  }
  if (isChapter(meta)) meta = "";
  return { name, meta };
}

export function expertCaption(expert, facts) {
  const raw = String((expert && (expert.display_name || expert.name)) || "").trim();
  if (expert && expert.self) return "关于你";
  if (raw === "关于你") return raw;
  const owned = (facts || []).filter((fact) => {
    if (fact && fact.superseded) return false;
    if (!expert) return true;
    return fact.expert === expert.name || fact.expert === expert.id;
  });
  if (owned.length && owned.every((fact) => speaker(fact.entity))) return "关于你";
  const parts = raw.replace(/等$/, "").split(/[、,]/).map((part) => part.trim()).filter(Boolean);
  if (parts.length && parts.every((part) => speaker(part))) return "关于你";
  return raw;
}

import { createNebula } from "./nebula.js";
import { createCanvasNebula } from "./nebula-canvas.js";
import { gl2Available } from "./nebula-gl1.js";
import { startSky } from "../sky/sky.js";

let canvas = document.getElementById("nebula-canvas");
const detail = document.getElementById("detail");
const recallBanner = document.getElementById("recall-banner");
const stateBanner = document.getElementById("state-banner");
const empty = document.getElementById("empty");

window.i18n = {
  getLocale() {
    return document.documentElement.lang.startsWith("en") ? "en" : "zh-CN";
  },
  t(key, vars) {
    const en = this.getLocale() === "en";
    if (key === "nebula.count") return en ? `${vars.n} facts` : `${vars.n} 条事实`;
    if (key === "nebula.new") return en ? "New" : "新";
    return key;
  },
  foreignName(name) {
    return String(name || "").replace(/、/g, ", ").replace(/等$/, "").trim();
  },
};

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;",
  }[ch]));
}

function enLocale() {
  return document.documentElement.lang.startsWith("en");
}

function hideDetail() {
  detail.hidden = true;
  detail.innerHTML = "";
}

function row(label, value) {
  return `<p class="row">${esc(label)} · <b>${esc(value)}</b></p>`;
}

function jump(id) {
  if (window.Android && Android.onOpenConversation) Android.onOpenConversation(id);
}

function showFact(fact) {
  const en = enLocale();
  const parts = [`<p class="statement">${esc(fact.statement || fact.value || "")}</p>`];
  if (fact.attr) parts.push(row(en ? "Attribute" : "属性", fact.attr));
  if (fact.value) parts.push(row(en ? "Value" : "取值", fact.value));
  if (fact.source_title) {
    parts.push(
      `<p class="row">${esc(en ? "Source" : "来源")} · <button type="button" data-jump="${esc(fact.conversation_id || "")}">${esc(fact.source_title)}</button></p>`,
    );
  }
  if (typeof fact.gate_score === "number" && !Number.isNaN(fact.gate_score)) {
    parts.push(row(en ? "Gate" : "闸门", fact.gate_score.toFixed(3)));
  }
  detail.hidden = false;
  detail.innerHTML = parts.join("");
  const button = detail.querySelector("[data-jump]");
  if (button) button.addEventListener("click", () => jump(button.getAttribute("data-jump") || ""));
  publish();
}

function showConversation(conversation) {
  const en = enLocale();
  detail.hidden = false;
  detail.innerHTML = `<p class="statement">${esc(conversation.title || "")}</p>`
    + `<p class="row">${esc(conversation.snippet || "")}</p>`
    + `<p class="row"><button type="button" data-jump="${esc(conversation.conversation_id || "")}">${esc(en ? "Open conversation" : "打开对话")}</button></p>`;
  const button = detail.querySelector("[data-jump]");
  if (button) button.addEventListener("click", () => jump(button.getAttribute("data-jump") || ""));
  publish();
}

function log(line) {
  const text = String(line || "");
  console.info(text);
  if (window.Android && Android.onLog) Android.onLog(text.slice(0, 500));
}

window.addEventListener("error", (event) => {
  log(`error ${event.message} ${event.filename || ""}:${event.lineno || 0}`);
});
window.addEventListener("unhandledrejection", (event) => {
  log(`rejection ${event.reason && event.reason.message ? event.reason.message : event.reason}`);
});

let lastFacts = [];
let noticed = false;

function replaceCanvas() {
  const next = document.createElement("canvas");
  next.id = "nebula-canvas";
  next.style.width = "100%";
  next.style.height = "100%";
  next.style.display = "block";
  next.style.touchAction = "none";
  canvas.replaceWith(next);
  canvas = next;
  return next;
}

function deadNebula() {
  return {
    kind: "dead",
    setData() {},
    resize() {},
    refreshLabels() {},
    highlight() { return { mounted: false, nodeIds: [] }; },
    focus() {},
    setMode() {},
    dispose() {},
    status() {
      return {
        renderer: "",
        version: "none",
        path: "canvas",
        zoom: 0,
        cameraZ: 0,
        cameraX: 0,
        fallback: "canvas",
        frames: 0,
        touches: 0,
        hitX: 0,
        hitY: 0,
        freshLabels: 0,
        kind: "dead",
      };
    },
  };
}

const hooks = {
  onHover() {},
  onSelect(data) {
    if (!data) return;
    if (data.kind === "fact" && data.fact) showFact(data.fact);
    else if (data.kind === "conversation" && data.conversation) showConversation(data.conversation);
    else if (data.kind === "expert") {
      const name = data.expertName || (data.expert && data.expert.name) || "";
      const fact = data.fact || lastFacts.find((item) => item.expert === name && !item.superseded) || lastFacts.find((item) => item.expert === name);
      if (fact) showFact(fact);
      else hideDetail();
    } else hideDetail();
  },
  onBroken(error) {
    log(`three broken ${error && error.message ? error.message : error}`);
    mountCanvas("render");
  },
  onVisualFail(report) {
    const flip = report && report.flip != null ? Number(report.flip).toFixed(3) : "?";
    const rough = report && report.rough != null ? Number(report.rough).toFixed(2) : "?";
    log(`nebula lattice flip=${flip} rough=${rough}`);
    mountCanvas("lattice");
  },
};

let nebula = null;

let mountingCanvas = false;

function mountCanvas(reason) {
  if (mountingCanvas) return nebula;
  if (nebula && nebula.kind === "canvas2d") return nebula;
  mountingCanvas = true;
  const previous = nebula;
  nebula = null;
  try {
    if (previous && previous.dispose) previous.dispose();
  } catch (error) {
    log(`dispose ${error && error.message ? error.message : error}`);
  }
  try {
    replaceCanvas();
    const next = createCanvasNebula(canvas, hooks);
    nebula = next;
    log(`fallback canvas2d ${reason || ""}`);
    if (!noticed && window.Android && Android.onNotice) {
      noticed = true;
      Android.onNotice("canvas2d");
    }
    if (lastPayload) applyMessage(lastPayload);
    publish();
    return next;
  } catch (error) {
    log(`canvas2d failed ${error && error.message ? error.message : error}`);
  } finally {
    mountingCanvas = false;
  }
  nebula = deadNebula();
  log(`fallback compose ${reason || ""}`);
  if (window.Android && Android.onFallback) Android.onFallback("canvas");
  if (!noticed && window.Android && Android.onNotice) {
    noticed = true;
    Android.onNotice("canvas");
  }
  publish();
  return null;
}

function boot() {
  const probe = gl2Available();
  log(`webgl2 probe ok=${probe.ok} renderer=${probe.renderer || ""} ${probe.reason || ""}`);
  if (probe.ok) {
    try {
      const created = createNebula(canvas, hooks);
      if (nebula && nebula.kind === "canvas2d") {
        try { if (created && created.dispose) created.dispose(); } catch (error) { log(String(error)); }
        return;
      }
      if (created && created.kind !== "dead") {
        nebula = created;
        log(`webgl2 renderer=${probe.renderer || ""}`);
        publish();
        return;
      }
    } catch (error) {
      log(`webgl2 init ${error && error.message ? error.message : error}`);
    }
  }
  if (!(nebula && (nebula.kind === "canvas2d" || nebula.kind === "three"))) mountCanvas(probe.reason || "no-webgl2");
}

let lastData = "";
let lastPayload = null;

function setLang(lang) {
  document.documentElement.lang = lang === "en" ? "en" : "zh-CN";
  empty.textContent = lang === "en"
    ? "No experts yet. After consolidation, facts become stars."
    : "还没有专家。巩固之后，事实会变成星。";
  if (nebula && nebula.refreshLabels) nebula.refreshLabels();
}

function showRecall(trace) {
  const text = trace && trace.banner ? String(trace.banner) : "";
  recallBanner.hidden = !text;
  recallBanner.textContent = text;
}

function showState(dim) {
  stateBanner.hidden = !dim;
  stateBanner.textContent = dim ? (enLocale() ? "Consolidating" : "巩固中") : "";
}

function applyMessage(msg) {
  if (!nebula) return;
  if (msg.lang) setLang(msg.lang);
  const data = msg.data || { experts: [], facts: [], conversations: [], links: [] };
  lastFacts = data.facts || [];
  const raw = JSON.stringify(data);
  if (raw !== lastData) {
    nebula.setData(data);
    lastData = raw;
  }
  empty.hidden = (data.experts || []).length > 0;
  const dim = msg.mode === "dim" || msg.mode === "paused";
  nebula.setMode(dim ? "dim" : "full");
  if (window.sky && window.sky.setMode) window.sky.setMode(dim ? "dim" : "full");
  showState(dim);
  if (msg.recall && msg.recall.mounted) {
    nebula.highlight(msg.recall);
    showRecall(msg.recall);
  } else if (msg.recall) {
    nebula.highlight({ mounted: false, matched_facts: [] });
    showRecall(null);
  }
  if (msg.focus && nebula.focus) nebula.focus(msg.focus);
  if (msg.openFact) {
    const fact = (data.facts || []).find((item) => item.id === msg.openFact);
    if (fact) showFact(fact);
  }
  if (nebula.resize) nebula.resize();
  paintChrome(msg);
  publish();
}

function paintChrome(msg) {
  const params = new URLSearchParams(location.search);
  if (!params.get("shot")) return;
  document.body.classList.add("shot");
  const en = (msg.lang || "zh") === "en";
  const labels = en
    ? [["chat", "Chat"], ["nebula", "Nebula"], ["consolidate", "Consolidate"], ["library", "Library"]]
    : [["chat", "对话"], ["nebula", "星云"], ["consolidate", "巩固"], ["library", "记忆库"]];
  const tab = msg.tab || "nebula";
  const title = document.getElementById("chrome-title");
  title.textContent = (labels.find((item) => item[0] === tab) || labels[1])[1];
  const nav = document.getElementById("chrome-nav");
  nav.innerHTML = labels.map(([id, label]) => `<span class="${id === tab ? "on" : ""}">${label}</span>`).join("");
}

function snapshot() {
  const sky = window.sky || {};
  const body = nebula && nebula.status ? nebula.status() : {
    renderer: "",
    version: "none",
    path: "canvas",
    zoom: 0,
    cameraZ: 0,
    cameraX: 0,
    fallback: "canvas",
    frames: 0,
    touches: 0,
    hitX: 0,
    hitY: 0,
    freshLabels: 0,
    kind: "dead",
  };
  body.detail = Boolean(detail && !detail.hidden);
  body.detailText = detail ? String(detail.innerText || "").slice(0, 240) : "";
  body.skyRenderer = sky.renderer || "";
  body.skyVersion = sky.version || "";
  if (!body.renderer && body.skyRenderer) body.renderer = body.skyRenderer;
  return body;
}

function publish() {
  try {
    const payload = JSON.stringify(snapshot());
    window.__nebulaStatus = payload;
    if (window.Android && Android.onStatus) Android.onStatus(payload);
  } catch (error) {
    log(`status ${error && error.message ? error.message : error}`);
  }
}

window.nebulaHost = {
  apply(payload) {
    const msg = typeof payload === "string" ? JSON.parse(payload) : payload;
    lastPayload = msg;
    applyMessage(msg);
  },
  resize() {
    if (nebula && nebula.resize) nebula.resize();
  },
  probe() {
    publish();
    return window.__nebulaStatus || "";
  },
};

window.addEventListener("resize", () => {
  if (nebula && nebula.resize) nebula.resize();
});
setInterval(publish, 400);

try {
  startSky();
} catch (error) {
  log(`sky init ${error && error.message ? error.message : error}`);
}
boot();

const shot = new URLSearchParams(location.search).get("shot");
if (shot) {
  fetch(`./shot/${shot}.json`).then((res) => res.json()).then((msg) => {
    applyMessage(msg);
    window.__shotReady = true;
  }).catch((error) => {
    empty.hidden = false;
    empty.textContent = String(error);
    window.__shotReady = true;
  });
}

import { createNebula } from "./nebula.js";

const canvas = document.getElementById("nebula-canvas");
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
}

function showConversation(conversation) {
  const en = enLocale();
  detail.hidden = false;
  detail.innerHTML = `<p class="statement">${esc(conversation.title || "")}</p>`
    + `<p class="row">${esc(conversation.snippet || "")}</p>`
    + `<p class="row"><button type="button" data-jump="${esc(conversation.conversation_id || "")}">${esc(en ? "Open conversation" : "打开对话")}</button></p>`;
  const button = detail.querySelector("[data-jump]");
  if (button) button.addEventListener("click", () => jump(button.getAttribute("data-jump") || ""));
}

const nebula = createNebula(canvas, {
  onHover() {},
  onSelect(data) {
    if (!data) return;
    if (data.kind === "fact" && data.fact) showFact(data.fact);
    else if (data.kind === "conversation" && data.conversation) showConversation(data.conversation);
    else hideDetail();
  },
});

let lastData = "";

function setLang(lang) {
  document.documentElement.lang = lang === "en" ? "en" : "zh-CN";
  empty.textContent = lang === "en"
    ? "No experts yet. After consolidation, facts become stars."
    : "还没有专家。巩固之后，事实会变成星。";
  if (nebula.refreshLabels) nebula.refreshLabels();
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
  if (msg.lang) setLang(msg.lang);
  const data = msg.data || { experts: [], facts: [], conversations: [], links: [] };
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

window.nebulaHost = {
  apply(payload) {
    const msg = typeof payload === "string" ? JSON.parse(payload) : payload;
    applyMessage(msg);
  },
  resize() {
    if (nebula.resize) nebula.resize();
  },
};

window.addEventListener("resize", () => {
  if (nebula.resize) nebula.resize();
});

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

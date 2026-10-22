const state = {
  conversations: [],
  currentId: null,
  selected: new Set(),
  view: "chat",
  facts: [],
  sourceIds: [],
  previewId: null,
  preview: null,
  job: null,
  sending: false,
  nebula: null,
  nebulaData: null,
  star: null,
  proposal: null,
};

const $ = (id) => document.getElementById(id);
const t = (key, vars) => window.i18n.t(key, vars);
const tx = (value) => window.i18n.tx(value);

function fmtLoss(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(2) : "";
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || t("error.request"));
  return data;
}

function showError(error) {
  window.alert(tx(error.message || String(error)));
}

function parseExtra(message) {
  if (!message || !message.extra) return null;
  try { return JSON.parse(message.extra); } catch (error) { return null; }
}

function formatEta(seconds) {
  if (seconds == null) return "";
  const whole = Math.max(0, Math.round(seconds));
  const min = Math.floor(whole / 60);
  const sec = whole % 60;
  return min ? t("eta.min", { min, sec }) : t("eta.sec", { sec });
}

function setView(view) {
  state.view = view;
  $("chat-view").hidden = view !== "chat";
  $("consolidate-view").hidden = view !== "consolidate";
  $("nebula-view").hidden = view !== "nebula";
  $("memory-view").hidden = view !== "memory";
  const column = $("nebula-column");
  const host = view === "nebula" ? $("nebula-host") : $("recall-host");
  if (column && host && column.parentElement !== host) host.appendChild(column);
  document.querySelectorAll(".nav").forEach((button) => button.classList.remove("active"));
  const nav = { chat: "nav-chat", consolidate: "nav-consolidate", nebula: "nav-nebula", memory: "memory-tab" }[view];
  if ($(nav)) $(nav).classList.add("active");
  const labels = { chat: "nav.chat", consolidate: "nav.consolidate", nebula: "nav.nebula", memory: "nav.memory" };
  $("eyebrow").textContent = t(labels[view] || "nav.chat");
  if (state.nebula) state.nebula.resize();
}

async function refreshHealth() {
  const health = await api("/api/health");
  const ready = health.models && health.models.state === "ready";
  $("boot").hidden = ready;
  $("app").hidden = !ready;
  if (!ready) {
    const detail = health.models && health.models.detail ? ` (${health.models.detail})` : "";
    const failed = health.models && health.models.state === "error";
    $("boot-text").textContent = failed
      ? t("boot.failedDetail", { detail: (health.models && health.models.detail) || t("boot.network") })
      : `${t("boot.loading")}${detail}`;
  }
  const device = health.device === "cpu" ? "CPU" : health.device === "cuda" ? "CUDA" : health.device === "mps" ? "MPS" : health.device;
  $("device-label").textContent = t("device.line", { device });
  if (health.job) state.job = health.job;
  renderJobBar();
  if (state.view === "consolidate") renderStages();
  return health;
}

function renderJobBar() {
  const bar = $("jobbar");
  const job = state.job;
  if (!job) {
    bar.hidden = true;
    return;
  }
  bar.hidden = false;
  const loss = job.loss == null ? "" : ` · loss ${fmtLoss(job.loss)}`;
  const eta = job.status === "running" && job.eta_seconds != null ? ` · ${formatEta(job.eta_seconds)}` : "";
  let action = "";
  if (job.status === "running") action = `<button id="job-cancel" type="button">${esc(t("action.cancel"))}</button>`;
  if (job.status === "cancelled" || job.status === "failed") action = `<button id="job-resume" type="button">${esc(t("action.resume"))}</button>`;
  bar.innerHTML = `<div><strong>${esc(tx(job.message || job.status))}</strong><div class="muted">${esc(t("job.line", { epoch: job.epoch || 0, max: job.max_epochs || 12 }))}${esc(loss)}${esc(eta)}</div></div><div>${action}</div>`;
  const cancel = $("job-cancel");
  const resume = $("job-resume");
  if (cancel) cancel.onclick = () => api(`/api/jobs/${job.id}/cancel`, { method: "POST", body: "{}" }).then(refreshHealth).catch(showError);
  if (resume) resume.onclick = () => api(`/api/jobs/${job.id}/resume`, { method: "POST", body: "{}" }).then(() => openConsolidate()).catch(showError);
  syncSky();
}

function syncSky() {
  const training = Boolean(state.job && state.job.status === "running") || Boolean(state.preview && state.preview.status === "running");
  const mode = training ? "dim" : "full";
  if (window.sky) window.sky.setMode(mode);
  if (state.nebula && state.nebula.setMode) state.nebula.setMode(mode);
}

function activeTrace() {
  if (state.preview && state.preview.status === "running") return state.preview;
  if (state.job && (state.job.stages || state.job.events)) return state.job;
  if (state.preview) return state.preview;
  return null;
}

function renderStages() {
  const trace = activeTrace();
  const stages = (trace && trace.stages) || [
    { id: "select", state: "pending" },
    { id: "extract", state: "pending" },
    { id: "gate", state: "pending" },
    { id: "build", state: "pending" },
    { id: "train", state: "pending" },
    { id: "recall", state: "pending" },
    { id: "register", state: "pending" },
    { id: "done", state: "pending" },
  ];
  const width = 1080;
  const height = 300;
  const points = stages.map((stage, index) => {
    const along = stages.length <= 1 ? 0.5 : index / (stages.length - 1);
    return {
      stage,
      x: 78 + along * (width - 156),
      y: 92 + Math.sin(along * Math.PI) * -28,
    };
  });
  const lines = points.slice(1).map((point, index) => {
    const prev = points[index];
    const lit = point.stage.state === "done" || point.stage.state === "active" || prev.stage.state === "done";
    return `<line x1="${prev.x.toFixed(1)}" y1="${prev.y.toFixed(1)}" x2="${point.x.toFixed(1)}" y2="${point.y.toFixed(1)}" stroke="${lit ? "rgba(242,210,145,0.85)" : "rgba(180,198,220,0.28)"}" stroke-width="${lit ? 1.6 : 1}" />`;
  }).join("");
  const stars = points.map((point) => {
    const stateName = point.stage.state || "pending";
    const on = stateName === "done" || stateName === "active";
    const r = stateName === "active" ? 7 : on ? 5.2 : 3.6;
    const fill = stateName === "active" ? "#f2d291" : on ? "#d7e6ff" : "rgba(180,198,220,0.45)";
    const linesOf = labelLines(stageTitle(point.stage));
    const text = linesOf.map((line, lineIndex) => `<tspan x="${point.x.toFixed(1)}" dy="${lineIndex === 0 ? 0 : 16}">${esc(line)}</tspan>`).join("");
    return `<g>
      <circle cx="${point.x.toFixed(1)}" cy="${point.y.toFixed(1)}" r="${r + 10}" fill="${fill}" opacity="${on ? 0.18 : 0.05}" />
      <circle cx="${point.x.toFixed(1)}" cy="${point.y.toFixed(1)}" r="${r}" fill="${fill}" />
      <text class="${on ? "star-label on" : ""}" x="${point.x.toFixed(1)}" y="${(point.y + 28).toFixed(1)}" text-anchor="middle">${text}</text>
    </g>`;
  }).join("");
  $("stage-list").innerHTML = `<svg class="constellation" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(t("stage.constellation"))}">${lines}${stars}</svg>`;
  renderFeed(trace);
  renderLoss(trace);
  const reviewing = state.preview && state.preview.status === "done" && !(state.job && state.job.status === "running");
  $("fact-editor").hidden = !reviewing;
  if (reviewing) renderFacts();
  syncSky();
}

function labelLines(text) {
  const value = String(text || "");
  if (!value.includes(" ") || value.length <= 12) return [value];
  const words = value.split(" ");
  let split = 1;
  let best = Infinity;
  for (let index = 1; index < words.length; index += 1) {
    const score = Math.max(words.slice(0, index).join(" ").length, words.slice(index).join(" ").length);
    if (score < best) {
      best = score;
      split = index;
    }
  }
  return [words.slice(0, split).join(" "), words.slice(split).join(" ")];
}

function stageTitle(stage) {
  const key = `stage.${stage && stage.id}`;
  const label = t(key);
  if (label !== key) return label;
  return tx((stage && stage.title) || (stage && stage.id) || "");
}

function renderFeed(trace) {
  const events = (trace && trace.events) || [];
  const recall = (trace && trace.recall) || [];
  const shown = events.filter((event) => event.stage !== "train").slice(-24);
  if (trace && trace.error) {
    $("stage-feed").innerHTML = `<article class="event"><strong>${esc(t("feed.failed"))}</strong><div class="muted">${esc(tx(trace.error))}</div></article>`;
    return;
  }
  if (!shown.length && !recall.length) {
    $("stage-feed").innerHTML = `<div class="empty">${esc(t("empty.feed"))}</div>`;
    return;
  }
  const rows = shown.map((event) => {
    if (event.stage === "select") return `<article class="event"><strong>${esc(t("feed.selected"))}</strong><div>${esc(event.title || event.conversation_id || "")}</div><div class="muted">${esc(event.chars == null ? "" : t("feed.chars", { n: event.chars }))}</div></article>`;
    if (event.stage === "extract") {
      const note = event.duplicate ? t("feed.duplicate") : tx(event.note || event.how || "");
      return `<article class="event"><strong>${esc(event.statement || t("feed.extracted"))}</strong><div class="muted">${esc([event.entity, event.attr, event.value].filter(Boolean).join(" · "))} ${esc(note)}</div></article>`;
    }
    if (event.stage === "gate") {
      const skipped = String(event.gate || "").startsWith("skip_");
      return `<article class="event"><strong>${esc(event.statement || "")}</strong><div class="badge ${skipped ? "" : "write"}">${esc(skipped ? t("feed.skip") : t("feed.write"))} · ${esc(tx(event.gate_reason || event.gate || ""))}</div></article>`;
    }
    if (event.stage === "build") return `<article class="event"><strong>${esc(t("feed.samples"))}</strong><div class="muted">${esc(t("feed.sampleLine", { facts: event.facts, rows: event.rows }))}</div></article>`;
    if (event.stage === "recall") return `<article class="event"><strong>${esc(t("feed.recall"))}</strong><div class="muted">${esc(t("feed.recallLine", { hits: event.hits, total: event.total }))}</div></article>`;
    if (event.stage === "register") return `<article class="event"><strong>${esc(t("feed.registered", { name: event.expert || "" }))}</strong><div class="muted">${esc(t("feed.keys", { n: event.keys }))}</div></article>`;
    return `<article class="event"><strong>${esc(tx(event.stage || ""))}</strong><div class="muted">${esc(tx(event.detail || event.statement || ""))}</div></article>`;
  });
  recall.forEach((item) => {
    rows.push(`<article class="event"><strong>${item.hit ? t("feed.hit") : t("feed.miss")} · ${esc(item.question || "")}</strong><div class="muted">${esc(t("feed.expect", { gold: item.gold, answer: item.answer }))}</div></article>`);
  });
  $("stage-feed").innerHTML = rows.join("");
}

function renderLoss(trace) {
  const card = $("loss-card");
  const curve = (trace && trace.loss_curve) || [];
  const train = ((trace && trace.stages) || []).find((stage) => stage.id === "train");
  const points = curve.length ? curve : ((train && train.items) || []).filter((item) => item && item.loss != null);
  if (!points.length) {
    card.hidden = true;
    return;
  }
  card.hidden = false;
  const width = 560;
  const height = 240;
  const padL = 52;
  const padR = 18;
  const padT = 16;
  const padB = 36;
  const losses = points.map((point) => Number(point.loss));
  const min = Math.min(...losses);
  const max = Math.max(...losses, min + 0.5);
  const span = Math.max(0.05, max - min);
  const finished = trace && (trace.status === "done" || trace.status === "cancelled" || trace.status === "failed");
  const maxEpoch = finished
    ? Math.max(2, ...points.map((point) => Number(point.epoch) || 1))
    : Math.max(12, ...points.map((point) => Number(point.epoch) || 1), Number(trace && trace.max_epochs) || 1);
  const xOf = (epoch) => padL + ((epoch - 1) / Math.max(1, maxEpoch - 1)) * (width - padL - padR);
  const yOf = (loss) => padT + (1 - (loss - min) / span) * (height - padT - padB);
  const poly = points.map((point) => `${xOf(Number(point.epoch) || 1).toFixed(1)},${yOf(Number(point.loss)).toFixed(1)}`).join(" ");
  const dots = points.map((point) => `<circle cx="${xOf(Number(point.epoch) || 1).toFixed(1)}" cy="${yOf(Number(point.loss)).toFixed(1)}" r="4.5" fill="#f2d291" filter="url(#loss-glow)" />`).join("");
  const yTicks = [max, min + span / 2, min].map((loss) => {
    const y = yOf(loss);
    return `<line x1="${padL}" y1="${y.toFixed(1)}" x2="${width - padR}" y2="${y.toFixed(1)}" stroke="rgba(183,215,255,0.12)" />
      <text x="${padL - 8}" y="${(y + 4).toFixed(1)}" text-anchor="end">${fmtLoss(loss)}</text>`;
  }).join("");
  const xTicks = [1, Math.round(maxEpoch / 2), maxEpoch].map((epoch) => {
    const x = xOf(epoch);
    return `<text x="${x.toFixed(1)}" y="${height - 10}" text-anchor="middle">${epoch}</text>`;
  }).join("");
  const last = points[points.length - 1];
  const eta = trace && trace.eta_seconds != null ? formatEta(trace.eta_seconds) : "";
  const seconds = last.seconds == null ? "" : Number(last.seconds).toFixed(1);
  const area = `${padL},${height - padB} ${poly} ${xOf(Number(last.epoch) || 1).toFixed(1)},${height - padB}`;
  card.innerHTML = `<strong>${esc(t("loss.title"))}</strong><div class="muted">${esc(t("loss.line", { epoch: last.epoch, loss: fmtLoss(last.loss), seconds, eta }))}</div>
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(t("loss.curve"))}">
      <defs>
        <linearGradient id="loss-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="rgba(242,210,145,0.28)" />
          <stop offset="100%" stop-color="rgba(242,210,145,0)" />
        </linearGradient>
        <filter id="loss-glow" x="-40%" y="-40%" width="180%" height="180%">
          <feGaussianBlur stdDeviation="3.4" result="blur" />
          <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>
      <line x1="${padL}" y1="${padT}" x2="${padL}" y2="${height - padB}" stroke="rgba(183,215,255,0.35)" />
      <line x1="${padL}" y1="${height - padB}" x2="${width - padR}" y2="${height - padB}" stroke="rgba(183,215,255,0.35)" />
      ${yTicks}
      ${xTicks}
      <polygon points="${area}" fill="url(#loss-fill)" />
      <polyline fill="none" stroke="rgba(242,210,145,0.28)" stroke-width="7" points="${poly}" />
      <polyline fill="none" stroke="#f2d291" stroke-width="2.2" filter="url(#loss-glow)" points="${poly}" />
      ${dots}
    </svg>`;
}

async function loadConversations() {
  const data = await api("/api/conversations");
  state.conversations = data.conversations;
  if (!state.currentId && state.conversations[0]) state.currentId = state.conversations[0].id;
  renderConversations();
  if (state.view === "chat" && state.currentId) await openConversation(state.currentId, false);
}

function dayKey(value) {
  const date = new Date(value || "");
  if (Number.isNaN(date.getTime())) return "earlier";
  const today = new Date();
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const day = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const diff = Math.round((start - day) / 86400000);
  if (diff === 0) return "today";
  return day.toISOString().slice(0, 10);
}

function dayLabel(key, sample) {
  if (key === "today") return t("list.today");
  if (key === "earlier") return t("list.earlier");
  const date = new Date(sample || key);
  if (Number.isNaN(date.getTime())) return t("list.earlier");
  const locale = window.i18n.getLocale() === "en" ? "en" : "zh-CN";
  return date.toLocaleDateString(locale, { month: "short", day: "numeric" });
}

function renderConversations() {
  const root = $("conv-list");
  if (!state.conversations.length) {
    root.innerHTML = `<div class="empty">${esc(t("empty.conversations"))}</div>`;
    return;
  }
  const groups = [];
  const seen = new Map();
  state.conversations.forEach((conv) => {
    const key = dayKey(conv.updated_at || conv.created_at);
    if (!seen.has(key)) {
      const group = { key, items: [] };
      seen.set(key, group);
      groups.push(group);
    }
    seen.get(key).items.push(conv);
  });
  root.innerHTML = groups.map((group) => {
    const sample = group.items[0] && (group.items[0].updated_at || group.items[0].created_at);
    const rows = group.items.map((conv) => `
      <div class="conv ${conv.id === state.currentId && state.view === "chat" ? "active" : ""}">
        <input type="checkbox" data-pick="${esc(conv.id)}" ${state.selected.has(conv.id) ? "checked" : ""} aria-label="${esc(t("pick.conversation", { title: tx(conv.title) }))}" />
        <button class="link" type="button" data-open="${esc(conv.id)}" title="${esc(tx(conv.title || t("title.new")))}">${esc(tx(conv.title || t("title.new")))}</button>
      </div>
    `).join("");
    return `<div class="conv-day">${esc(dayLabel(group.key, sample))}</div>${rows}`;
  }).join("");
  root.querySelectorAll("[data-open]").forEach((button) => {
    button.onclick = () => openConversation(button.dataset.open, true);
  });
  root.querySelectorAll("[data-pick]").forEach((box) => {
    box.onchange = () => {
      if (box.checked) state.selected.add(box.dataset.pick);
      else state.selected.delete(box.dataset.pick);
    };
  });
}

function proposalCard(extra) {
  const proposal = extra && extra.proposal;
  if (!proposal) return "";
  return `<div class="proposal">
    <p>${esc(t("proposal.old", { text: proposal.old_statement }))}</p>
    <p>${esc(t("proposal.next", { text: proposal.new_statement }))}</p>
    <button type="button" data-confirm-correction="${esc(proposal.fact_id)}">${esc(t("action.retrain"))}</button>
  </div>`;
}

function recallTrace(extra) {
  return extra && extra.trace ? extra.trace : null;
}

function chipLabel(trace) {
  if (!trace || !trace.mounted) return t("chip.idle");
  const row = (trace.experts || []).find((item) => item.name === trace.mounted_expert);
  const name = row ? row.display_name : trace.mounted_expert;
  const facts = (trace.matched_facts || []).map((fact) => fact.value || fact.attr).filter(Boolean);
  return facts.length ? t("chip.from", { name, facts: facts.join(t("list.sep")) }) : t("chip.whole", { name });
}

function chipTitle(trace) {
  if (!trace) return "";
  const tau = trace.thresholds && trace.thresholds.router_tau;
  const scores = (trace.experts || []).map((item) => `${item.display_name || item.name} ${Number(item.sim).toFixed(3)}${item.considered ? "" : t("chip.notCompared")}`).join(" · ");
  const head = tau == null ? tx(trace.reason_text || "") : t("chip.tau", { tau: Number(tau).toFixed(3) });
  return [head, scores, tx(trace.reason_text || "")].filter(Boolean).join("\n");
}

function recallChip(msg, extra) {
  const trace = recallTrace(extra);
  if (!trace) return "";
  const idle = trace.mounted ? "" : " idle";
  return `<button type="button" class="recall-chip${idle}" data-recall="${esc(msg.id)}" title="${esc(chipTitle(trace))}">${esc(chipLabel(trace))}</button>`;
}

function bannerText(trace) {
  if (!trace || !trace.mounted) return t("banner.idle");
  const row = (trace.experts || []).find((item) => item.name === trace.mounted_expert);
  const name = row ? row.display_name : trace.mounted_expert;
  const tau = trace.thresholds || {};
  const matched = (trace.matched_facts || []).map((fact) => t("banner.fact", {
    label: fact.attr || fact.value || t("fact.this"),
    q: Number(fact.question_sim).toFixed(3),
    a: Number(fact.attr_sim).toFixed(3),
  }));
  const which = matched.length
    ? t("banner.facts", { list: matched.join(t("list.sep")), tau: Number(tau.fact_tau).toFixed(3) })
    : t("banner.keyOnly");
  const sim = row ? t("banner.sim", { sim: Number(row.sim).toFixed(3), tau: Number(tau.router_tau).toFixed(3) }) : "";
  return t("banner.mounted", { name, which, sim });
}

function showRecallBanner(trace) {
  const banner = $("recall-banner");
  banner.hidden = false;
  banner.classList.toggle("idle", !trace || !trace.mounted);
  banner.textContent = bannerText(trace);
}

function reducedMotion() {
  return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function flyToStars(fromEl, points) {
  if (reducedMotion() || !fromEl || !points || !points.length) return;
  const comet = $("recall-comet");
  const start = fromEl.getBoundingClientRect();
  const canvas = $("nebula-canvas").getBoundingClientRect();
  const point = points[0];
  const x0 = start.left + start.width / 2;
  const y0 = start.top + Math.min(24, start.height / 2);
  const x1 = canvas.left + point.x;
  const y1 = canvas.top + point.y;
  comet.hidden = false;
  const t0 = performance.now();
  function step(now) {
    const t = Math.min(1, (now - t0) / 720);
    const ease = 1 - (1 - t) * (1 - t);
    comet.style.left = `${x0 + (x1 - x0) * ease}px`;
    comet.style.top = `${y0 + (y1 - y0) * ease}px`;
    if (t < 1) requestAnimationFrame(step);
    else comet.hidden = true;
  }
  requestAnimationFrame(step);
}

function revealText(node, full) {
  if (!node || reducedMotion()) return;
  node.textContent = "";
  let index = 0;
  const timer = window.setInterval(() => {
    index = Math.min(full.length, index + Math.max(1, Math.ceil(full.length / 26)));
    node.textContent = full.slice(0, index);
    if (index >= full.length) window.clearInterval(timer);
  }, 36);
}

async function playRecall(trace, fromEl, streamNode, fullText) {
  state.recall = trace || null;
  showRecallBanner(trace);
  if (!state.nebula) return;
  const lit = state.nebula.highlight(trace);
  if (streamNode && fullText) revealText(streamNode, fullText);
  if (!lit.mounted) return;
  await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  const points = lit.nodeIds.map((id) => state.nebula.screenPoint(id)).filter(Boolean);
  flyToStars(fromEl, points);
}

async function openConversation(id, switchView, revealId) {
  state.currentId = id;
  if (switchView) {
    setView("chat");
    $("title").textContent = t("title.new");
  }
  const conv = await api(`/api/conversations/${id}`);
  if (state.view === "chat") $("title").textContent = tx(conv.title) || t("title.new");
  const box = $("messages");
  if (!conv.messages.length) {
    box.innerHTML = `<div class="empty">${esc(t("empty.chat"))}</div>`;
  } else {
    box.innerHTML = conv.messages.map((msg) => {
      const extra = parseExtra(msg);
      if (msg.role === "user") return `<div class="bubble user">${esc(msg.content)}</div>`;
      const memory = msg.fired ? "memory" : "";
      const label = tx(msg.expert_label || (msg.fired ? "记忆" : "基座"));
      const sim = msg.sim == null ? "" : ` · ${Number(msg.sim).toFixed(2)}`;
      const shown = msg.role === "assistant" ? tx(msg.content) : msg.content;
      const card = extra && extra.kind === "correction_proposal" ? proposalCard(extra) : "";
      const chip = recallChip(msg, extra);
      return `<div class="bubble assistant" data-msg="${esc(msg.id)}"><div class="body">${esc(shown)}</div>${card}${chip}<div class="route ${memory}" title="${esc(tx(msg.reason || ""))}">${esc(label)}${esc(sim)}</div></div>`;
    }).join("");
  }
  box.querySelectorAll("[data-confirm-correction]").forEach((button) => {
    button.onclick = async () => {
      const bubble = button.closest(".bubble");
      const messages = conv.messages.filter((msg) => parseExtra(msg) && parseExtra(msg).proposal && parseExtra(msg).proposal.fact_id === button.dataset.confirmCorrection);
      const extra = messages.length ? parseExtra(messages[messages.length - 1]) : null;
      if (!extra) return;
      try {
        const data = await api("/api/corrections/commit", {
          method: "POST",
          body: JSON.stringify({ proposal: extra.proposal, conversation_id: id }),
        });
        state.job = data.job;
        state.preview = null;
        await openConsolidate();
      } catch (error) {
        showError(error);
      }
    };
  });
  box.querySelectorAll("[data-recall]").forEach((button) => {
    button.onclick = async () => {
      const message = conv.messages.find((item) => item.id === button.dataset.recall);
      const trace = recallTrace(parseExtra(message));
      if (!trace) return;
      if (state.view !== "chat" && state.view !== "nebula") setView("chat");
      await ensureNebula();
      const bubble = button.closest(".bubble");
      await playRecall(trace, bubble, null, "");
    };
  });
  box.scrollTop = box.scrollHeight;
  renderConversations();
  if (revealId) {
    const message = conv.messages.find((item) => item.id === revealId);
    const bubble = box.querySelector(`[data-msg="${revealId}"]`);
    const trace = recallTrace(parseExtra(message));
    if (bubble && trace) {
      await ensureNebula();
      const body = bubble.querySelector(".body");
      await playRecall(trace, bubble, body, message.content || "");
    }
  }
}

async function loadMemory() {
  setView("memory");
  $("title").textContent = t("title.memory");
  const data = await api("/api/experts");
  const root = $("memory-view");
  if (!data.experts.length) {
    root.innerHTML = `<div class="empty">${esc(t("empty.memory"))}</div>`;
    return;
  }
  root.innerHTML = data.experts.map((expert) => {
    const facts = (expert.facts || []).slice(0, 30).map((fact) => `<li>${fact.superseded ? esc(t("fact.superseded")) : ""}${esc(fact.statement || fact.question || "")}</li>`).join("");
    const sources = (expert.sources || []).map((src) => esc(src.title || src.id)).join(t("list.sep")) || t("fact.noSource");
    return `<article class="card">
      <h3>${esc(expert.display_name || expert.name)}</h3>
      <div class="muted">${esc(expert.name)} · ${esc(t("fact.activeCount", { n: expert.n_facts }))}</div>
      <p>${esc(t("fact.sources", { names: sources }))}</p>
      <ul>${facts || `<li>${esc(t("empty.factText"))}</li>`}</ul>
      <button class="danger" type="button" data-del="${esc(expert.name)}">${esc(t("action.delete"))}</button>
    </article>`;
  }).join("");
  root.querySelectorAll("[data-del]").forEach((button) => {
    button.onclick = async () => {
      if (!window.confirm(t("memory.deleteConfirm"))) return;
      try {
        await api(`/api/experts/${button.dataset.del}`, { method: "DELETE" });
        await loadMemory();
      } catch (error) {
        showError(error);
      }
    };
  });
}

function renderFacts() {
  const root = $("fact-list");
  if (!state.facts.length) {
    root.innerHTML = `<div class="empty">${esc(t("empty.facts"))}</div>`;
    $("editor-commit").disabled = true;
    return;
  }
  $("editor-commit").disabled = !state.facts.some((fact) => fact.selected);
  root.innerHTML = state.facts.map((fact, index) => {
    const skipped = String(fact.gate || "").startsWith("skip_");
    if (skipped) fact.selected = false;
    return `
    <div class="fact">
      <label><span><input type="checkbox" data-sel="${index}" ${skipped ? "disabled" : ""} ${fact.selected ? "checked" : ""} /> ${esc(t("fact.write"))}</span></label>
      ${fact.gate_reason ? `<div class="badge ${skipped ? "" : "write"}">${esc(tx(fact.gate_reason))}</div>` : ""}
      <label>${esc(t("fact.statement"))}<textarea data-field="statement" data-i="${index}">${esc(fact.statement)}</textarea></label>
      <div class="row">
        <label>${esc(t("fact.entity"))}<input data-field="entity" data-i="${index}" value="${esc(fact.entity)}" /></label>
        <label>${esc(t("fact.attr"))}<input data-field="attr" data-i="${index}" value="${esc(fact.attr)}" /></label>
      </div>
      <div class="row">
        <label>${esc(t("fact.value"))}<input data-field="value" data-i="${index}" value="${esc(fact.value)}" /></label>
        <label>${esc(t("fact.answer"))}<input data-field="answer" data-i="${index}" value="${esc(fact.answer)}" /></label>
      </div>
      <label>${esc(t("fact.question"))}<input data-field="question" data-i="${index}" value="${esc(fact.question)}" /></label>
    </div>`;
  }).join("");
  root.querySelectorAll("[data-sel]").forEach((box) => {
    box.onchange = () => {
      const fact = state.facts[Number(box.dataset.sel)];
      if (String(fact.gate || "").startsWith("skip_")) {
        fact.selected = false;
        box.checked = false;
        return;
      }
      fact.selected = box.checked;
    };
  });
  root.querySelectorAll("[data-field]").forEach((input) => {
    input.oninput = () => { state.facts[Number(input.dataset.i)][input.dataset.field] = input.value; };
  });
}

async function openConsolidate() {
  setView("consolidate");
  $("title").textContent = t("title.consolidate");
  renderStages();
}

function factScoreLine(fact) {
  const trace = state.recall;
  const gate = trace && trace.fact_gate;
  if (!gate || !gate.facts) return "";
  const row = gate.facts.find((item) => item.node_id === fact.id || item.fact_id === fact.fact_id);
  if (!row) return "";
  const tau = trace.thresholds && trace.thresholds.fact_tau;
  const status = row.passed && trace.mounted ? t("fact.gateHit") : t("fact.gateMiss");
  const threshold = tau == null ? "" : ` · ${t("fact.threshold", { tau: Number(tau).toFixed(3) })}`;
  return `<div>${status} · ${t("fact.qscore", { q: Number(row.question_sim).toFixed(3), a: Number(row.attr_sim).toFixed(3) })}${threshold}</div><div class="muted">${esc(tx(trace.wording || ""))}</div>`;
}

function expertScoreLine(expert) {
  const trace = state.recall;
  if (!trace || !trace.experts) return "";
  const row = trace.experts.find((item) => item.name === expert.name);
  if (!row) return "";
  const tau = trace.thresholds && trace.thresholds.router_tau;
  const threshold = tau == null ? "" : ` · ${t("fact.threshold", { tau: Number(tau).toFixed(3) })}`;
  const role = row.chosen ? t("expert.mounted") : row.considered ? t("expert.compared") : t("expert.out");
  return `<div>${t("expert.key", { sim: Number(row.sim).toFixed(3) })}${threshold} · ${role}</div>`;
}

async function ensureNebula() {
  const data = await api("/api/nebula");
  state.nebulaData = data;
  $("nebula-empty").hidden = Boolean((data.facts || []).length || (data.experts || []).length);
  if (!state.nebula) {
    const mod = await import("./nebula.js");
    state.nebula = mod.createNebula($("nebula-canvas"), {
      onHover(payload, x, y) {
        const tip = $("nebula-tip");
        if (!payload) {
          tip.hidden = true;
          return;
        }
        tip.hidden = false;
        tip.style.left = `${x + 14}px`;
        tip.style.top = `${y + 14}px`;
        if (payload.kind === "fact") {
          tip.innerHTML = `<strong>${esc(payload.fact.statement || payload.fact.value)}</strong><div class="muted">${payload.fact.superseded ? t("fact.dim") : t("fact.live")} · ${esc(payload.fact.expert_label || "")}</div>${factScoreLine(payload.fact)}`;
        } else if (payload.kind === "conversation") {
          tip.innerHTML = `<strong>${esc(payload.conversation.title)}</strong><div class="muted">${esc(payload.conversation.snippet || "")}</div>`;
        } else if (payload.kind === "expert") {
          tip.innerHTML = `<strong>${esc(payload.expert.display_name || payload.expert.name)}</strong>${expertScoreLine(payload.expert)}`;
        }
      },
      onSelect(payload) {
        if (payload.kind === "fact") openStar(payload.fact);
        if (payload.kind === "conversation") openConversationSnippet(payload.conversation);
      },
    });
  }
  state.nebula.setData(data);
  state.nebula.resize();
  if (state.recall) state.nebula.highlight(state.recall);
}

async function openNebula() {
  setView("nebula");
  $("title").textContent = t("title.nebula");
  await ensureNebula();
}

function openConversationSnippet(conversation) {
  $("modal-title").textContent = conversation.title || t("title.source");
  $("modal-body").innerHTML = `<p>${esc(conversation.snippet || t("empty.snippet"))}</p>`;
  $("modal-commit").hidden = true;
  $("modal").hidden = false;
}

function openStar(fact) {
  state.star = fact;
  state.proposal = null;
  $("modal-title").textContent = fact.superseded ? t("title.starOld") : t("title.star");
  const snippets = (fact.snippets || []).map((item) => `<div class="snippet"><strong>${esc(item.title || "")}</strong><div>${esc(item.text || "")}</div></div>`).join("");
  const status = fact.superseded ? t("star.statusOff") : t("star.statusOn");
  const editor = fact.writable ? `<label class="muted">${esc(t("star.edit"))}</label><input id="star-value" type="text" value="" placeholder="${esc(t("star.placeholder"))}" />` : `<p class="muted">${esc(t("star.locked"))}</p>`;
  $("modal-body").innerHTML = `
    <p>${esc(fact.statement || "")}</p>
    <p class="muted">${esc(fact.expert_label || fact.expert)} · ${esc(fact.entity)} · ${esc(fact.attr)} · ${esc(status)}</p>
    ${snippets || `<div class="snippet">${esc(t("empty.snippets"))}</div>`}
    <div id="star-proposal"></div>
    ${editor}`;
  $("modal-commit").hidden = !fact.writable;
  $("modal-commit").textContent = t("action.preview");
  $("modal").hidden = false;
}

async function commitStar() {
  const fact = state.star;
  if (!fact) return;
  if (!state.proposal) {
    const value = ($("star-value") && $("star-value").value || "").trim();
    if (!value) return showError(new Error(t("star.needValue")));
    const data = await api("/api/corrections/propose", {
      method: "POST",
      body: JSON.stringify({ fact_id: fact.fact_id, new_value: value, text: value }),
    });
    if (!data.proposal) return showError(new Error(t("star.noProposal")));
    state.proposal = data.proposal;
    $("star-proposal").innerHTML = `<div class="proposal"><p>${esc(t("proposal.old", { text: data.proposal.old_statement }))}</p><p>${esc(t("proposal.next", { text: data.proposal.new_statement }))}</p></div>`;
    $("modal-commit").textContent = t("action.retrain");
    return;
  }
  const data = await api("/api/corrections/commit", {
    method: "POST",
    body: JSON.stringify({ proposal: state.proposal, conversation_id: state.currentId }),
  });
  state.job = data.job;
  state.proposal = null;
  $("modal").hidden = true;
  await openConsolidate();
}

$("new-chat").onclick = async () => {
  try {
    const conv = await api("/api/conversations", { method: "POST", body: JSON.stringify({ title: t("title.new") }) });
    state.currentId = conv.id;
    await loadConversations();
    await openConversation(conv.id, true);
    $("input").focus();
  } catch (error) { showError(error); }
};

$("nav-chat").onclick = () => {
  setView("chat");
  if (state.currentId) openConversation(state.currentId, false).catch(showError);
};
$("nav-consolidate").onclick = () => openConsolidate();
$("nav-nebula").onclick = () => openNebula().catch(showError);
$("memory-tab").onclick = () => loadMemory().catch(showError);

$("consolidate").onclick = async () => {
  const ids = [...state.selected];
  if (!ids.length && state.currentId) ids.push(state.currentId);
  if (!ids.length) return showError(new Error(t("star.needChat")));
  state.sourceIds = ids;
  state.facts = [];
  state.job = null;
  await openConsolidate();
  $("stage-feed").innerHTML = `<div class="empty">${esc(t("empty.reading"))}</div>`;
  try {
    const started = await api("/api/consolidate/preview", { method: "POST", body: JSON.stringify({ conversation_ids: ids }) });
    state.previewId = started.id;
    state.preview = started;
    renderStages();
  } catch (error) {
    showError(error);
  }
};

$("editor-commit").onclick = async () => {
  try {
    const data = await api("/api/consolidate/commit", {
      method: "POST",
      body: JSON.stringify({ conversation_ids: state.sourceIds, facts: state.facts, preview_id: state.previewId }),
    });
    state.job = data.job;
    state.preview = null;
    renderStages();
    renderJobBar();
  } catch (error) { showError(error); }
};

$("modal-close").onclick = () => { $("modal").hidden = true; state.proposal = null; };
$("modal-commit").onclick = () => commitStar().catch(showError);

$("composer").onsubmit = async (event) => {
  event.preventDefault();
  const text = $("input").value.trim();
  if (!text || state.sending) return;
  state.sending = true;
  $("send").disabled = true;
  try {
    if (!state.currentId) {
      const conv = await api("/api/conversations", { method: "POST", body: JSON.stringify({ title: t("title.new") }) });
      state.currentId = conv.id;
    }
    $("input").value = "";
    const sent = await api(`/api/conversations/${state.currentId}/messages`, {
      method: "POST",
      body: JSON.stringify({ content: text }),
    });
    await loadConversations();
    await openConversation(state.currentId, true, sent.assistant && sent.assistant.id);
  } catch (error) {
    showError(error);
  } finally {
    state.sending = false;
    $("send").disabled = false;
    $("input").focus();
  }
};

$("input").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    $("composer").requestSubmit();
  }
});

async function pollWork() {
  if (state.previewId && state.preview && state.preview.status === "running") {
    try {
      state.preview = await api(`/api/consolidate/preview/${state.previewId}`);
      if (state.preview.status === "done") state.facts = state.preview.facts || [];
      if (state.view === "consolidate") renderStages();
    } catch (error) { /* 下一轮再试 */ }
  }
  if (state.job && state.job.id && (state.job.status === "running" || state.job.status === "cancelled")) {
    try {
      const job = await api(`/api/jobs/${state.job.id}`);
      const finished = state.job.status === "running" && job.status === "done";
      state.job = job;
      renderJobBar();
      if (state.view === "consolidate") renderStages();
      if (finished && state.view === "nebula") openNebula().catch(() => {});
    } catch (error) { /* 下一轮再试 */ }
  }
}

async function syncLocale() {
  try {
    const settings = await api("/api/settings");
    if (settings.locale === "zh-CN" || settings.locale === "en") {
      if (settings.locale !== window.i18n.getLocale()) window.i18n.setLocale(settings.locale);
      return;
    }
    await api("/api/settings", { method: "POST", body: JSON.stringify({ locale: window.i18n.getLocale() }) });
  } catch (error) { /* 没有后端时仍用本机语言 */ }
}

function bindLanguage() {
  document.querySelectorAll("[data-locale]").forEach((button) => {
    button.onclick = () => {
      const next = button.getAttribute("data-locale");
      if (!next || next === window.i18n.getLocale()) return;
      window.i18n.setLocale(next);
      api("/api/settings", { method: "POST", body: JSON.stringify({ locale: window.i18n.getLocale() }) }).catch(() => {});
    };
  });
  window.i18n.onChange(() => {
    setView(state.view);
    renderJobBar();
    renderConversations();
    if (state.view === "chat" && state.currentId) openConversation(state.currentId, false).catch(showError);
    else if (state.view === "memory") loadMemory().catch(showError);
    else if (state.view === "nebula") openNebula().catch(showError);
    else if (state.view === "consolidate") renderStages();
    refreshHealth().catch(() => {});
  });
}

async function boot() {
  bindLanguage();
  await syncLocale();
  let opened = false;
  async function tick() {
    const health = await refreshHealth();
    const ready = health.models && health.models.state === "ready";
    if (ready && !opened) {
      opened = true;
      await loadConversations();
      await ensureNebula();
    }
    await pollWork();
  }
  try {
    await tick();
  } catch (error) {
    $("boot-text").textContent = error.message;
  }
  setInterval(() => { tick().catch(() => {}); }, 1000);
  window.addEventListener("resize", () => { if (state.nebula) state.nebula.resize(); });
}

boot();

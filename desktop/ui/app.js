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
  if (!res.ok) throw new Error(data.error || "请求失败");
  return data;
}

function showError(error) {
  window.alert(error.message || String(error));
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
  return min ? `约 ${min} 分 ${sec} 秒` : `约 ${sec} 秒`;
}

function setView(view) {
  state.view = view;
  $("chat-view").hidden = view !== "chat";
  $("consolidate-view").hidden = view !== "consolidate";
  $("nebula-view").hidden = view !== "nebula";
  $("memory-view").hidden = view !== "memory";
  document.querySelectorAll(".nav").forEach((button) => button.classList.remove("active"));
  const nav = { chat: "nav-chat", consolidate: "nav-consolidate", nebula: "nav-nebula", memory: "memory-tab" }[view];
  if ($(nav)) $(nav).classList.add("active");
  const labels = { chat: "对话", consolidate: "巩固", nebula: "星云", memory: "记忆库" };
  $("eyebrow").textContent = labels[view] || "";
}

async function refreshHealth() {
  const health = await api("/api/health");
  const ready = health.models && health.models.state === "ready";
  $("boot").hidden = ready;
  $("app").hidden = !ready;
  if (!ready) {
    const detail = health.models && health.models.detail ? `（${health.models.detail}）` : "";
    const failed = health.models && health.models.state === "error";
    $("boot-text").textContent = failed
      ? `模型下载失败：${health.models.detail || "请检查网络"}`
      : `正在准备本地模型${detail}`;
  }
  const device = health.device === "cpu" ? "CPU" : health.device === "cuda" ? "CUDA" : health.device === "mps" ? "MPS" : health.device;
  $("device-label").textContent = `本机推理 · ${device}`;
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
  const loss = job.loss == null ? "" : ` · loss ${job.loss}`;
  const eta = job.status === "running" && job.eta_seconds != null ? ` · ${formatEta(job.eta_seconds)}` : "";
  let action = "";
  if (job.status === "running") action = `<button id="job-cancel" type="button">取消</button>`;
  if (job.status === "cancelled" || job.status === "failed") action = `<button id="job-resume" type="button">继续训练</button>`;
  bar.innerHTML = `<div><strong>${esc(job.message || job.status)}</strong><div class="muted">第 ${esc(job.epoch || 0)} / ${esc(job.max_epochs || 12)} 轮${esc(loss)}${esc(eta)}</div></div><div>${action}</div>`;
  const cancel = $("job-cancel");
  const resume = $("job-resume");
  if (cancel) cancel.onclick = () => api(`/api/jobs/${job.id}/cancel`, { method: "POST", body: "{}" }).then(refreshHealth).catch(showError);
  if (resume) resume.onclick = () => api(`/api/jobs/${job.id}/resume`, { method: "POST", body: "{}" }).then(() => openConsolidate()).catch(showError);
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
    { id: "select", title: "选择对话", state: "pending", detail: "勾选对话后开始" },
    { id: "extract", title: "抽取事实", state: "pending" },
    { id: "gate", title: "写门", state: "pending" },
    { id: "build", title: "编训练样本", state: "pending" },
    { id: "train", title: "训练 LoRA", state: "pending" },
    { id: "recall", title: "回忆检查", state: "pending" },
    { id: "register", title: "登记专家", state: "pending" },
    { id: "done", title: "完成", state: "pending" },
  ];
  $("stage-list").innerHTML = stages.map((stage) => `
    <li class="stage ${esc(stage.state || "pending")}">
      <span class="dot"></span>
      <div><strong>${esc(stage.title || stage.id)}</strong><div class="muted">${esc(stage.detail || "")}</div></div>
    </li>
  `).join("");
  renderFeed(trace);
  renderLoss(trace);
  const reviewing = state.preview && state.preview.status === "done" && !(state.job && state.job.status === "running");
  $("fact-editor").hidden = !reviewing;
  if (reviewing) renderFacts();
}

function renderFeed(trace) {
  const events = (trace && trace.events) || [];
  const recall = (trace && trace.recall) || [];
  const shown = events.filter((event) => event.stage !== "train").slice(-24);
  if (trace && trace.error) {
    $("stage-feed").innerHTML = `<article class="event"><strong>这一步没有完成</strong><div class="muted">${esc(trace.error)}</div></article>`;
    return;
  }
  if (!shown.length && !recall.length) {
    $("stage-feed").innerHTML = `<div class="empty">巩固开始后，这里会按真实进度出现：选中的对话、抽出的事实、写门为什么跳过、训练损失、回忆是否答对、登记了哪位专家。</div>`;
    return;
  }
  const rows = shown.map((event) => {
    if (event.stage === "select") return `<article class="event"><strong>选中对话</strong><div>${esc(event.title || event.conversation_id || "")}</div><div class="muted">${esc(event.chars == null ? "" : `${event.chars} 字`)}</div></article>`;
    if (event.stage === "extract") {
      const note = event.duplicate ? "同一事实已经抽过" : (event.note || event.how || "");
      return `<article class="event"><strong>${esc(event.statement || "抽到一条事实")}</strong><div class="muted">${esc([event.entity, event.attr, event.value].filter(Boolean).join(" · "))} ${esc(note)}</div></article>`;
    }
    if (event.stage === "gate") {
      const skipped = String(event.gate || "").startsWith("skip_");
      return `<article class="event"><strong>${esc(event.statement || "")}</strong><div class="badge ${skipped ? "" : "write"}">${esc(skipped ? "跳过" : "写入")} · ${esc(event.gate_reason || event.gate || "")}</div></article>`;
    }
    if (event.stage === "build") return `<article class="event"><strong>训练样本</strong><div class="muted">${esc(event.facts)} 条事实，${esc(event.rows)} 条样本</div></article>`;
    if (event.stage === "recall") return `<article class="event"><strong>回忆检查</strong><div class="muted">${esc(event.hits)}/${esc(event.total)} 条主问题答对</div></article>`;
    if (event.stage === "register") return `<article class="event"><strong>已登记 ${esc(event.expert || "")}</strong><div class="muted">路由键 ${esc(event.keys)} 条</div></article>`;
    return `<article class="event"><strong>${esc(event.stage || "")}</strong><div class="muted">${esc(event.detail || event.statement || "")}</div></article>`;
  });
  recall.forEach((item) => {
    rows.push(`<article class="event"><strong>${item.hit ? "答对" : "未答对"} · ${esc(item.question || "")}</strong><div class="muted">期望 ${esc(item.gold)} · 回答 ${esc(item.answer)}</div></article>`);
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
  const width = 360;
  const height = 120;
  const pad = 16;
  const losses = points.map((point) => Number(point.loss));
  const min = Math.min(...losses);
  const max = Math.max(...losses);
  const span = Math.max(0.02, max - min);
  const poly = points.map((point, index) => {
    const x = pad + (index / Math.max(1, points.length - 1)) * (width - pad * 2);
    const y = pad + (1 - (Number(point.loss) - min) / span) * (height - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const last = points[points.length - 1];
  const eta = trace && trace.eta_seconds != null ? formatEta(trace.eta_seconds) : "";
  card.innerHTML = `<strong>训练损失</strong><div class="muted">第 ${esc(last.epoch)} 轮 · loss ${esc(last.loss)} · 这一轮 ${esc(last.seconds)}s ${esc(eta)}</div>
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="损失曲线">
      <polyline fill="none" stroke="#f0c36a" stroke-width="2.4" points="${poly}" />
    </svg>`;
}

async function loadConversations() {
  const data = await api("/api/conversations");
  state.conversations = data.conversations;
  if (!state.currentId && state.conversations[0]) state.currentId = state.conversations[0].id;
  renderConversations();
  if (state.view === "chat" && state.currentId) await openConversation(state.currentId, false);
}

function renderConversations() {
  const root = $("conv-list");
  if (!state.conversations.length) {
    root.innerHTML = `<div class="empty">还没有对话</div>`;
    return;
  }
  root.innerHTML = state.conversations.map((conv) => `
    <div class="conv ${conv.id === state.currentId && state.view === "chat" ? "active" : ""}">
      <input type="checkbox" data-pick="${esc(conv.id)}" ${state.selected.has(conv.id) ? "checked" : ""} aria-label="选择${esc(conv.title)}" />
      <button class="link" type="button" data-open="${esc(conv.id)}">${esc(conv.title || "新对话")}</button>
    </div>
  `).join("");
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
    <p>原来：${esc(proposal.old_statement)}</p>
    <p>改为：${esc(proposal.new_statement)}</p>
    <button type="button" data-confirm-correction="${esc(proposal.fact_id)}">确认并重新训练</button>
  </div>`;
}

async function openConversation(id, switchView) {
  state.currentId = id;
  if (switchView) {
    setView("chat");
    $("title").textContent = "新对话";
  }
  const conv = await api(`/api/conversations/${id}`);
  if (state.view === "chat") $("title").textContent = conv.title || "新对话";
  const box = $("messages");
  if (!conv.messages.length) {
    box.innerHTML = `<div class="empty">直接输入即可。回答旁边会标出这次用的是基座还是某条记忆。若某条记忆不对，就在这里说出正确的取值，或到星云里点那颗星。</div>`;
  } else {
    box.innerHTML = conv.messages.map((msg) => {
      const extra = parseExtra(msg);
      if (msg.role === "user") return `<div class="bubble user">${esc(msg.content)}</div>`;
      const memory = msg.fired ? "memory" : "";
      const label = msg.expert_label || (msg.fired ? "记忆" : "基座");
      const sim = msg.sim == null ? "" : ` · ${Number(msg.sim).toFixed(2)}`;
      const card = extra && extra.kind === "correction_proposal" ? proposalCard(extra) : "";
      return `<div class="bubble assistant">${esc(msg.content)}${card}<div class="route ${memory}" title="${esc(msg.reason || "")}">${esc(label)}${esc(sim)}</div></div>`;
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
  box.scrollTop = box.scrollHeight;
  renderConversations();
}

async function loadMemory() {
  setView("memory");
  $("title").textContent = "记忆库";
  const data = await api("/api/experts");
  const root = $("memory-view");
  if (!data.experts.length) {
    root.innerHTML = `<div class="empty">还没有巩固过的记忆。勾选左侧对话后点「巩固所选」。</div>`;
    return;
  }
  root.innerHTML = data.experts.map((expert) => {
    const facts = (expert.facts || []).slice(0, 30).map((fact) => `<li>${fact.superseded ? "（已取代）" : ""}${esc(fact.statement || fact.question || "")}</li>`).join("");
    const sources = (expert.sources || []).map((src) => esc(src.title || src.id)).join("、") || "未记录";
    return `<article class="card">
      <h3>${esc(expert.display_name || expert.name)}</h3>
      <div class="muted">${esc(expert.name)} · ${esc(expert.n_facts)} 条仍生效的事实</div>
      <p>来源对话：${sources}</p>
      <ul>${facts || "<li>没有可显示的事实文本</li>"}</ul>
      <button class="danger" type="button" data-del="${esc(expert.name)}">删除这条记忆</button>
    </article>`;
  }).join("");
  root.querySelectorAll("[data-del]").forEach((button) => {
    button.onclick = async () => {
      if (!window.confirm("删除后，相关问题会回到基座回答，不会误挂到其他记忆。确定删除？")) return;
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
    root.innerHTML = `<div class="empty">没有抽到可写入的事实。换一段更明确的陈述再试。</div>`;
    $("editor-commit").disabled = true;
    return;
  }
  $("editor-commit").disabled = !state.facts.some((fact) => fact.selected);
  root.innerHTML = state.facts.map((fact, index) => {
    const skipped = String(fact.gate || "").startsWith("skip_");
    if (skipped) fact.selected = false;
    return `
    <div class="fact">
      <label><span><input type="checkbox" data-sel="${index}" ${skipped ? "disabled" : ""} ${fact.selected ? "checked" : ""} /> 写入这条</span></label>
      ${fact.gate_reason ? `<div class="badge ${skipped ? "" : "write"}">${esc(fact.gate_reason)}</div>` : ""}
      <label>陈述<textarea data-field="statement" data-i="${index}">${esc(fact.statement)}</textarea></label>
      <div class="row">
        <label>实体<input data-field="entity" data-i="${index}" value="${esc(fact.entity)}" /></label>
        <label>属性<input data-field="attr" data-i="${index}" value="${esc(fact.attr)}" /></label>
      </div>
      <div class="row">
        <label>取值<input data-field="value" data-i="${index}" value="${esc(fact.value)}" /></label>
        <label>答案<input data-field="answer" data-i="${index}" value="${esc(fact.answer)}" /></label>
      </div>
      <label>问题<input data-field="question" data-i="${index}" value="${esc(fact.question)}" /></label>
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
  $("title").textContent = "巩固";
  renderStages();
}

async function openNebula() {
  setView("nebula");
  $("title").textContent = "知识星云";
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
          tip.innerHTML = `<strong>${esc(payload.fact.statement || payload.fact.value)}</strong><div class="muted">${payload.fact.superseded ? "已取代" : "生效"} · ${esc(payload.fact.expert_label || "")}</div>`;
        } else if (payload.kind === "conversation") {
          tip.innerHTML = `<strong>${esc(payload.conversation.title)}</strong><div class="muted">${esc(payload.conversation.snippet || "")}</div>`;
        } else if (payload.kind === "expert") {
          tip.innerHTML = `<strong>${esc(payload.expert.display_name || payload.expert.name)}</strong>`;
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
}

function openConversationSnippet(conversation) {
  $("modal-title").textContent = conversation.title || "来源对话";
  $("modal-body").innerHTML = `<p>${esc(conversation.snippet || "没有摘录")}</p>`;
  $("modal-commit").hidden = true;
  $("modal").hidden = false;
}

function openStar(fact) {
  state.star = fact;
  state.proposal = null;
  $("modal-title").textContent = fact.superseded ? "已取代的事实" : "一条记忆";
  const snippets = (fact.snippets || []).map((item) => `<div class="snippet"><strong>${esc(item.title || "")}</strong><div>${esc(item.text || "")}</div></div>`).join("");
  const status = fact.superseded ? "已取代，星云里这颗星会变暗" : "生效，参与路由和回答";
  const editor = fact.writable ? `<label class="muted">若这条不对，写下正确取值</label><input id="star-value" type="text" value="" placeholder="新的取值" />` : `<p class="muted">研究专家不能在这里改。</p>`;
  $("modal-body").innerHTML = `
    <p>${esc(fact.statement || "")}</p>
    <p class="muted">${esc(fact.expert_label || fact.expert)} · ${esc(fact.entity)} · ${esc(fact.attr)} · ${esc(status)}</p>
    ${snippets || `<div class="snippet">没有留下原对话摘录。</div>`}
    <div id="star-proposal"></div>
    ${editor}`;
  $("modal-commit").hidden = !fact.writable;
  $("modal-commit").textContent = "预览纠正";
  $("modal").hidden = false;
}

async function commitStar() {
  const fact = state.star;
  if (!fact) return;
  if (!state.proposal) {
    const value = ($("star-value") && $("star-value").value || "").trim();
    if (!value) return showError(new Error("先写下新的取值"));
    const data = await api("/api/corrections/propose", {
      method: "POST",
      body: JSON.stringify({ fact_id: fact.fact_id, new_value: value, text: value }),
    });
    if (!data.proposal) return showError(new Error("没有生成纠正"));
    state.proposal = data.proposal;
    $("star-proposal").innerHTML = `<div class="proposal"><p>原来：${esc(data.proposal.old_statement)}</p><p>改为：${esc(data.proposal.new_statement)}</p></div>`;
    $("modal-commit").textContent = "确认并重新训练";
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
    const conv = await api("/api/conversations", { method: "POST", body: "{}" });
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
  if (!ids.length) return showError(new Error("请先选择至少一则对话"));
  state.sourceIds = ids;
  state.facts = [];
  state.job = null;
  await openConsolidate();
  $("stage-feed").innerHTML = `<div class="empty">正在读取选中的对话…</div>`;
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
      const conv = await api("/api/conversations", { method: "POST", body: "{}" });
      state.currentId = conv.id;
    }
    $("input").value = "";
    await api(`/api/conversations/${state.currentId}/messages`, {
      method: "POST",
      body: JSON.stringify({ content: text }),
    });
    await loadConversations();
    await openConversation(state.currentId, true);
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

async function boot() {
  let opened = false;
  async function tick() {
    const health = await refreshHealth();
    const ready = health.models && health.models.state === "ready";
    if (ready && !opened) {
      opened = true;
      await loadConversations();
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

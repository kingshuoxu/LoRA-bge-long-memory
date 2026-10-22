const state = {
  conversations: [],
  currentId: null,
  selected: new Set(),
  view: "chat",
  facts: [],
  sourceIds: [],
  job: null,
  sending: false,
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
  state.job = health.job;
  renderJob();
  return health;
}

function renderJob() {
  const bar = $("jobbar");
  const job = state.job;
  if (!job || job.status === "done" && !bar.dataset.hold) {
    if (!job || job.status === "done") {
      bar.hidden = !job || job.status !== "done";
    }
  }
  if (!job) {
    bar.hidden = true;
    return;
  }
  const active = job.status === "running" || job.status === "cancelled" || job.status === "failed" || job.status === "done";
  bar.hidden = !active;
  const loss = job.loss == null ? "" : ` · loss ${job.loss}`;
  const best = job.best_loss == null ? "" : ` · 最好 ${job.best_loss}`;
  let action = "";
  if (job.status === "running") action = `<button id="job-cancel" type="button">取消</button>`;
  if (job.status === "cancelled" || job.status === "failed") action = `<button id="job-resume" type="button">继续训练</button>`;
  bar.innerHTML = `<div><strong>${esc(job.message || job.status)}</strong><div class="muted">第 ${esc(job.epoch || 0)} / ${esc(job.max_epochs || 12)} 轮${esc(loss)}${esc(best)}</div></div><div>${action}</div>`;
  const cancel = $("job-cancel");
  const resume = $("job-resume");
  if (cancel) cancel.onclick = () => api(`/api/jobs/${job.id}/cancel`, { method: "POST", body: "{}" }).then(refreshHealth).catch(showError);
  if (resume) resume.onclick = () => api(`/api/jobs/${job.id}/resume`, { method: "POST", body: "{}" }).then(refreshHealth).catch(showError);
  if (job.status === "done") {
    bar.dataset.hold = "1";
    setTimeout(() => { if (state.job && state.job.status === "done") bar.hidden = true; }, 6000);
  }
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
    <div class="conv ${conv.id === state.currentId ? "active" : ""}">
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

async function openConversation(id, switchView) {
  state.currentId = id;
  if (switchView) {
    state.view = "chat";
    $("chat-view").hidden = false;
    $("memory-view").hidden = true;
  }
  const conv = await api(`/api/conversations/${id}`);
  $("title").textContent = conv.title || "新对话";
  const box = $("messages");
  if (!conv.messages.length) {
    box.innerHTML = `<div class="empty">直接输入即可。回答旁边会标出这次用的是基座还是某条记忆。</div>`;
  } else {
    box.innerHTML = conv.messages.map((msg) => {
      if (msg.role === "user") return `<div class="bubble user">${esc(msg.content)}</div>`;
      const memory = msg.fired ? "memory" : "";
      const label = msg.expert_label || (msg.fired ? "记忆" : "基座");
      const sim = msg.sim == null ? "" : ` · ${Number(msg.sim).toFixed(2)}`;
      return `<div class="bubble assistant">${esc(msg.content)}<div class="route ${memory}" title="${esc(msg.reason || "")}">${esc(label)}${esc(sim)}</div></div>`;
    }).join("");
  }
  box.scrollTop = box.scrollHeight;
  renderConversations();
}

async function loadMemory() {
  state.view = "memory";
  $("chat-view").hidden = true;
  $("memory-view").hidden = false;
  $("title").textContent = "记忆库";
  const data = await api("/api/experts");
  const root = $("memory-view");
  if (!data.experts.length) {
    root.innerHTML = `<div class="empty">还没有巩固过的记忆。勾选左侧对话后点「巩固所选」。</div>`;
    return;
  }
  root.innerHTML = data.experts.map((expert) => {
    const facts = (expert.facts || []).slice(0, 30).map((fact) => `<li>${esc(fact.statement || fact.question || "")}</li>`).join("");
    const sources = (expert.sources || []).map((src) => esc(src.title || src.id)).join("、") || "未记录";
    return `<article class="card">
      <h3>${esc(expert.display_name || expert.name)}</h3>
      <div class="muted">${esc(expert.name)} · ${esc(expert.n_facts)} 条事实</div>
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
    $("modal-commit").disabled = true;
    return;
  }
  $("modal-commit").disabled = false;
  root.innerHTML = state.facts.map((fact, index) => {
    const skipped = String(fact.gate || "").startsWith("skip_");
    if (skipped) fact.selected = false;
    return `
    <div class="fact">
      <label><span><input type="checkbox" data-sel="${index}" ${skipped ? "disabled" : ""} ${fact.selected ? "checked" : ""} /> 写入这条</span></label>
      ${fact.gate_reason ? `<div class="badge">${esc(fact.gate_reason)}</div>` : ""}
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
    </div>
  `;
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

$("new-chat").onclick = async () => {
  try {
    const conv = await api("/api/conversations", { method: "POST", body: "{}" });
    state.currentId = conv.id;
    state.view = "chat";
    $("chat-view").hidden = false;
    $("memory-view").hidden = true;
    await loadConversations();
    await openConversation(conv.id, true);
    $("input").focus();
  } catch (error) { showError(error); }
};

$("memory-tab").onclick = () => loadMemory().catch(showError);

$("consolidate").onclick = async () => {
  const ids = [...state.selected];
  if (!ids.length && state.currentId) ids.push(state.currentId);
  if (!ids.length) return showError(new Error("请先选择至少一则对话"));
  $("modal").hidden = false;
  $("fact-list").innerHTML = `<div class="empty">正在抽取事实…</div>`;
  try {
    const data = await api("/api/consolidate/preview", { method: "POST", body: JSON.stringify({ conversation_ids: ids }) });
    state.facts = data.facts;
    state.sourceIds = ids;
    renderFacts();
  } catch (error) {
    $("modal").hidden = true;
    showError(error);
  }
};

$("modal-close").onclick = () => { $("modal").hidden = true; };
$("modal-commit").onclick = async () => {
  try {
    const data = await api("/api/consolidate/commit", {
      method: "POST",
      body: JSON.stringify({ conversation_ids: state.sourceIds, facts: state.facts }),
    });
    state.job = data.job;
    $("modal").hidden = true;
    renderJob();
  } catch (error) { showError(error); }
};

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

async function boot() {
  let opened = false;
  async function tick() {
    const health = await refreshHealth();
    const ready = health.models && health.models.state === "ready";
    if (ready && !opened) {
      opened = true;
      await loadConversations();
    }
  }
  try {
    await tick();
  } catch (error) {
    $("boot-text").textContent = error.message;
  }
  setInterval(() => { tick().catch(() => {}); }, 2000);
}

boot();

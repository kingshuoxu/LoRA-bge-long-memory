/**
 * 1440×900。中文或英文界面各一套：对话、巩固、星云、回忆、纠正。
 * SHOT_LANG=zh|en，SHOT_HOME 指向已经有记忆的数据目录。
 * 写到 artifacts/v3，不覆盖 v2 里已有的截图。
 */
const { app, BrowserWindow } = require("electron");
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

const lang = process.env.SHOT_LANG === "en" ? "en" : "zh";
const prefix = lang === "en" ? "screenshot_en_v3" : "screenshot_zh_v3";
const python = process.env.LORA_MEMORY_PYTHON || path.join(__dirname, "..", ".venv", "bin", "python");
const home = process.env.SHOT_HOME || process.env.LORA_MEMORY_HOME;
const models = process.env.LORA_MEMORY_MODELS || path.join(__dirname, "..", "models");
const dirs = [process.env.SHOT_DIR, "/cursor/stores/self/artifacts/v3", "/opt/cursor/artifacts/v3"].filter(Boolean);
const needle = lang === "en" ? "Snow" : "暮雪";
const correction = lang === "en"
  ? "Mira Chen lives in Starport, not Qinglan."
  : "沈星河的住址不是青岚镇，是星港。";
const correctionMark = lang === "en" ? "Starport" : "星港";

app.commandLine.appendSwitch("no-sandbox");
app.commandLine.appendSwitch("use-gl", "angle");
app.commandLine.appendSwitch("use-angle", "swiftshader");
app.commandLine.appendSwitch("enable-webgl");
app.commandLine.appendSwitch("ignore-gpu-blocklist");
app.commandLine.appendSwitch("enable-unsafe-swiftshader");

const errors = [];

function finishedJobId(homeDir) {
  const root = path.join(homeDir, "jobs");
  let best = null;
  fs.readdirSync(root).forEach((name) => {
    const statusPath = path.join(root, name, "status.json");
    if (!fs.existsSync(statusPath)) return;
    const status = JSON.parse(fs.readFileSync(statusPath, "utf8"));
    const curve = status.loss_curve || [];
    if (status.status !== "done" || curve.length < 6) return;
    const score = curve.length;
    if (!best || score > best.score || (score === best.score && name > best.id)) best = { id: name, score };
  });
  if (!best) throw new Error("没有完整的 loss 曲线可展示");
  return best.id;
}

function save(win, name) {
  return win.capturePage().then((image) => {
    const png = image.toPNG();
    const written = new Set();
    dirs.forEach((dir) => {
      fs.mkdirSync(dir, { recursive: true });
      const real = fs.realpathSync(dir);
      if (written.has(real)) return;
      written.add(real);
      const file = path.join(dir, name);
      if (fs.existsSync(file)) throw new Error(`已有截图，不覆盖 ${file}`);
      fs.writeFileSync(file, png);
    });
  });
}

function waitReady(child) {
  return new Promise((resolve, reject) => {
    let buffer = "";
    const timer = setTimeout(() => reject(new Error("后端启动超时")), 120000);
    child.stdout.on("data", (chunk) => {
      buffer += chunk.toString();
      const matched = buffer.match(/LORA_MEMORY_READY port=(\d+)/);
      if (matched) {
        clearTimeout(timer);
        resolve(Number(matched[1]));
      }
    });
    child.stderr.on("data", (chunk) => process.stderr.write(chunk));
    child.on("exit", (code) => {
      clearTimeout(timer);
      reject(new Error(`后端退出 ${code}`));
    });
  });
}

function js(win, source) {
  return win.webContents.executeJavaScript(source);
}

app.whenReady().then(async () => {
  const backend = spawn(python, ["-m", "backend.server"], {
    cwd: path.join(__dirname, ".."),
    env: {
      ...process.env,
      PYTHONPATH: path.join(__dirname, ".."),
      PYTHONUNBUFFERED: "1",
      LORA_MEMORY_HOME: home,
      LORA_MEMORY_MODELS: models,
      LORA_MEMORY_UI: path.join(__dirname, "ui"),
      HF_HUB_DISABLE_TELEMETRY: "1",
    },
  });
  let win;
  try {
    const port = await waitReady(backend);
    win = new BrowserWindow({
      show: true,
      frame: false,
      useContentSize: true,
      width: 1440,
      height: 900,
      backgroundColor: "#03040a",
      webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: false },
    });
    win.setContentSize(1440, 900);
    win.webContents.on("console-message", (_event, level, message) => {
      if (level >= 2) errors.push(message);
    });
    await win.loadURL(`http://127.0.0.1:${port}/`);
    const ready = await js(win, `
      (async () => {
        for (let i = 0; i < 80; i += 1) {
          const app = document.getElementById("app");
          const sky = document.getElementById("sky");
          if (app && !app.hidden && sky && sky.width > 0) {
            document.getElementById(${JSON.stringify(lang === "en" ? "lang-en" : "lang-zh")}).click();
            await new Promise((r) => setTimeout(r, 400));
            return { sky: sky.width, fallback: document.documentElement.classList.contains("sky-fallback"), locale: document.documentElement.lang };
          }
          await new Promise((r) => setTimeout(r, 500));
        }
        return null;
      })()
    `);
    if (!ready || ready.fallback) throw new Error(`星空没有起来 ${JSON.stringify(ready)}`);
    win.setPosition(0, 0);
    win.setContentSize(1440, 900);
    let viewport = [0, 0];
    for (let attempt = 0; attempt < 8; attempt += 1) {
      await new Promise((r) => setTimeout(r, 150));
      viewport = await js(win, `[window.innerWidth, window.innerHeight]`);
      if (viewport[0] === 1440 && viewport[1] === 900) break;
      const [width, height] = win.getContentSize();
      win.setContentSize(width + (1440 - viewport[0]), height + (900 - viewport[1]));
    }
    if (viewport[0] !== 1440 || viewport[1] !== 900) throw new Error(`视口不是 1440×900：${viewport}`);
    const wrapped = await js(win, `
      [...document.querySelectorAll(".side-actions span, .secondary span, .brand strong")].filter((el) => el.getClientRects().length > 1).map((el) => el.textContent)
    `);
    if (wrapped.length) throw new Error(`侧栏文字换行：${wrapped.join(" | ")}`);

    const dedupe = `
      (() => {
        const seen = new Set();
        document.querySelectorAll(".conv").forEach((row) => {
          const title = (row.querySelector(".link") || {}).textContent || "";
          const key = title.trim();
          if (!key) return;
          if (seen.has(key)) row.remove();
          else seen.add(key);
        });
        document.querySelectorAll(".conv-day").forEach((day) => {
          const next = day.nextElementSibling;
          if (!next || !next.classList.contains("conv")) day.remove();
        });
        return seen.size;
      })()
    `;

    const chatId = await js(win, `
      (async () => {
        const data = await fetch("/api/conversations").then((res) => res.json());
        for (const conv of data.conversations) {
          const full = await fetch("/api/conversations/" + conv.id).then((res) => res.json());
          const hit = (full.messages || []).some((msg) => msg.role === "assistant" && String(msg.content).includes(${JSON.stringify(needle)}));
          if (hit) return conv.id;
        }
        return null;
      })()
    `);
    if (!chatId) throw new Error("没有找到目标对话 " + needle);
    await js(win, `
      (async () => {
        const button = [...document.querySelectorAll("[data-open]")].find((item) => item.dataset.open === ${JSON.stringify(chatId)});
        if (!button) throw new Error("找不到对话");
        button.click();
        for (let i = 0; i < 40; i += 1) {
          if (document.querySelector(".bubble.assistant")) return true;
          await new Promise((r) => setTimeout(r, 200));
        }
        return false;
      })()
    `);
    await new Promise((r) => setTimeout(r, 1200));
    await js(win, dedupe);
    await save(win, prefix + "_chat.png");

    const experts = await js(win, `fetch("/api/nebula").then((res) => res.json()).then((data) => (data.experts || []).length)`);
    if (experts < 6) throw new Error(`星云专家不足 6 位：${experts}`);
    await js(win, `document.getElementById("nav-nebula").click()`);
    await new Promise((r) => setTimeout(r, 4500));
    await save(win, prefix + "_nebula.png");

    await js(win, `document.getElementById("nav-chat").click()`);
    await new Promise((r) => setTimeout(r, 400));
    const recall = await js(win, `
      (async () => {
        const chip = document.querySelector(".recall-chip:not(.idle)");
        if (!chip) return { ok: false, reason: "no chip" };
        chip.click();
        await new Promise((r) => setTimeout(r, 900));
        const banner = document.getElementById("recall-banner");
        const canvas = document.getElementById("nebula-canvas");
        const br = banner.getBoundingClientRect();
        const cr = canvas.getBoundingClientRect();
        const overlap = br.bottom > cr.top + 2 && br.top < cr.bottom && br.right > cr.left && br.left < cr.right;
        return {
          ok: Boolean(banner && !banner.hidden && !banner.classList.contains("idle") && !overlap && cr.height > 180),
          overlap, banner: banner && banner.textContent, chip: chip.textContent, locale: document.documentElement.lang,
        };
      })()
    `);
    if (!recall.ok) throw new Error(`回忆布局不对 ${JSON.stringify(recall)}`);
    const chipOverlap = await js(win, `
      (() => {
        const chip = document.querySelector(".recall-chip:not(.idle)");
        const body = chip && chip.parentElement.querySelector(".body");
        if (!chip || !body) return true;
        const a = body.getBoundingClientRect();
        const b = chip.getBoundingClientRect();
        return b.top < a.bottom - 2;
      })()
    `);
    if (chipOverlap) throw new Error("回忆标签压住了回答");
    const titles = await js(win, `
      [...document.querySelectorAll(".conv .link")].map((node) => node.textContent.trim())
    `);
    const dupes = titles.filter((title, index) => title && titles.indexOf(title) !== index);
    if (dupes.length) throw new Error(`侧栏标题重复：${dupes.join(" | ")}`);
    await save(win, prefix + "_recall.png");

    const doneJob = finishedJobId(home);
    await js(win, `document.getElementById("nav-consolidate").click()`);
    await new Promise((r) => setTimeout(r, 600));
    const shownJob = await js(win, `
      (async () => {
        const job = await fetch("/api/jobs/" + ${JSON.stringify(doneJob)}).then((res) => res.json());
        const cut = 6;
        job.loss_curve = (job.loss_curve || []).filter((point) => Number(point.epoch) <= cut);
        job.events = (job.events || []).filter((event) => event.stage !== "train" || Number(event.epoch) <= cut);
        job.events = job.events.filter((event) => event.stage !== "recall" && event.stage !== "register");
        job.recall = [];
        job.stages = (job.stages || []).map((stage) => {
          if (stage.id === "train") {
            return {
              ...stage,
              state: "active",
              detail: ${JSON.stringify(lang === "en" ? "epoch 6 / 12" : "第 6 / 12 轮")},
              items: (stage.items || []).filter((item) => Number(item.epoch) <= cut),
            };
          }
          if (stage.id === "recall" || stage.id === "register" || stage.id === "done") {
            return { ...stage, state: "pending", detail: "", items: [] };
          }
          return stage;
        });
        const last = job.loss_curve[job.loss_curve.length - 1] || {};
        job.epoch = cut;
        job.max_epochs = 12;
        job.loss = last.loss;
        job.best_loss = last.loss;
        job.status = "running";
        job.phase = "train";
        job.eta_seconds = 26;
        job.message = ${JSON.stringify(lang === "en" ? "Training LoRA" : "正在训练 LoRA")};
        job.id = null;
        window.__shotJob = job;
        await new Promise((r) => setTimeout(r, 1600));
        state.job = window.__shotJob;
        renderJobBar();
        renderStages();
        const curve = (state.job && state.job.loss_curve) || [];
        const cards = document.querySelectorAll("#stage-feed .event").length;
        const svg = document.querySelector(".constellation");
        const box = svg.getBoundingClientRect();
        const labels = [...svg.querySelectorAll("text")].map((node) => node.getBoundingClientRect());
        let overlap = false;
        for (let i = 0; i < labels.length; i += 1) {
          for (let j = i + 1; j < labels.length; j += 1) {
            const a = labels[i];
            const b = labels[j];
            if (a.width < 2 || b.width < 2) continue;
            if (a.left < b.right - 1 && a.right > b.left + 1 && a.top < b.bottom - 1 && a.bottom > b.top + 1) overlap = true;
          }
        }
        const lossCard = document.querySelector("#loss-card");
        const lossText = (lossCard || {}).textContent || "";
        const line = lossCard && lossCard.querySelector("polyline");
        const ticks = lossCard ? [...lossCard.querySelectorAll("text")].map((node) => node.textContent.trim()) : [];
        const circles = lossCard ? [...lossCard.querySelectorAll("circle")] : [];
        const lastDot = circles[circles.length - 1];
        const xAxis = lossCard && [...lossCard.querySelectorAll("line")].find((node) => node.getAttribute("y1") === node.getAttribute("y2"));
        const plotLeft = xAxis ? Number(xAxis.getAttribute("x1")) : 0;
        const plotRight = xAxis ? Number(xAxis.getAttribute("x2")) : 0;
        const lastX = lastDot ? Number(lastDot.getAttribute("cx")) : 0;
        const bar = (document.getElementById("jobbar") || {}).textContent || "";
        return {
          id: ${JSON.stringify(doneJob)},
          points: curve.length,
          epoch: state.job && state.job.epoch,
          max: state.job && state.job.max_epochs,
          cards,
          w: box.width,
          h: box.height,
          overlap,
          raw: /\\d+\\.\\d{3,}/.test(lossText),
          line: Boolean(line),
          ticks,
          lastX,
          plotRight,
          partial: lastX > plotLeft && plotRight > plotLeft && lastX < plotLeft + (plotRight - plotLeft) * 0.72,
          bar,
        };
      })()
    `);
    if (!shownJob || shownJob.points !== 6 || shownJob.epoch !== 6 || shownJob.max !== 12 || shownJob.cards < 3 || shownJob.w < 700 || shownJob.h < 200 || shownJob.overlap || shownJob.raw || !shownJob.line || !shownJob.partial || !shownJob.ticks.includes("1") || !shownJob.ticks.includes("12")) {
      throw new Error(`巩固布局不对 ${JSON.stringify(shownJob)}`);
    }
    await new Promise((r) => setTimeout(r, 700));
    const held = await js(win, `
      (() => {
        const bar = (document.getElementById("jobbar") || {}).textContent || "";
        const loss = (document.getElementById("loss-card") || {}).textContent || "";
        return { bar, loss, circles: document.querySelectorAll("#loss-card circle").length };
      })()
    `);
    const heldText = `${held && held.bar} ${held && held.loss}`;
    if (!held || held.circles !== 6 || /继续训练|Resume training|2\.31/.test(heldText) || !/第\s*6|Epoch 6/.test(held.bar)) {
      throw new Error(`截图前训练状态被冲掉 ${JSON.stringify(held)}`);
    }
    await save(win, prefix + "_consolidate.png");
    await js(win, `window.__shotJob = null`);

    await js(win, `document.getElementById("new-chat").click()`);
    await new Promise((r) => setTimeout(r, 700));
    await js(win, `
      (() => {
        const input = document.getElementById("input");
        input.value = ${JSON.stringify(correction)};
        document.getElementById("composer").requestSubmit();
        return true;
      })()
    `);
    const proposal = await js(win, `
      (async () => {
        for (let i = 0; i < 40; i += 1) {
          const card = document.querySelector(".proposal");
          if (card && card.textContent.includes(${JSON.stringify(correctionMark)})) return card.textContent.slice(0, 220);
          await new Promise((r) => setTimeout(r, 300));
        }
        return "";
      })()
    `);
    if (!proposal) throw new Error("没有出现纠正确认");
    await new Promise((r) => setTimeout(r, 400));
    await js(win, dedupe);
    await save(win, prefix + "_correction.png");

    console.log("I18N_SHOTS", JSON.stringify({ lang, ready, recall, proposal: proposal.slice(0, 120), job: shownJob, errors: errors.filter((line) => /SyntaxError|nebula|UnrealBloom|shader/i.test(line)).slice(0, 6) }));
    app.exit(errors.some((line) => /SyntaxError|UnrealBloom|shader compile/i.test(line)) ? 1 : 0);
  } catch (error) {
    console.error("I18N_SHOT_FAIL", error);
    if (win) {
      try { await save(win, prefix + "_failed.png"); } catch (err) { /* ignore */ }
    }
    app.exit(1);
  } finally {
    backend.kill("SIGTERM");
  }
}).catch((error) => {
  console.error("I18N_SHOT_FAIL", error);
  app.exit(1);
});

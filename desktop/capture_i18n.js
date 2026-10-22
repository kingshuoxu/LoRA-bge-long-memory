/**
 * 1440×900。中文或英文界面各一套：对话、巩固、星云、回忆、纠正。
 * SHOT_LANG=zh|en，SHOT_HOME 指向已经有记忆的数据目录。
 * 不覆盖 artifacts/v2 里已有的截图。
 */
const { app, BrowserWindow } = require("electron");
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

const lang = process.env.SHOT_LANG === "en" ? "en" : "zh";
const prefix = lang === "en" ? "screenshot_en_serif" : "screenshot_zh_serif";
const python = process.env.LORA_MEMORY_PYTHON || path.join(__dirname, "..", ".venv", "bin", "python");
const home = process.env.SHOT_HOME || process.env.LORA_MEMORY_HOME;
const models = process.env.LORA_MEMORY_MODELS || path.join(__dirname, "..", "models");
const dirs = [process.env.SHOT_DIR, "/cursor/stores/self/artifacts/v2", "/opt/cursor/artifacts/v2"].filter(Boolean);
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
      width: 1440,
      height: 900,
      backgroundColor: "#070910",
      webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: false },
    });
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
    await save(win, prefix + "_chat.png");

    await js(win, `document.getElementById("nav-nebula").click()`);
    await new Promise((r) => setTimeout(r, 2200));
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
    await save(win, prefix + "_recall.png");

    if (lang === "zh") {
      await js(win, `document.getElementById("nav-consolidate").click()`);
      await new Promise((r) => setTimeout(r, 800));
      const curve = await js(win, `Boolean(state.job && (state.job.loss_curve || []).length)`);
      if (!curve) throw new Error("中文巩固没有真实 loss");
      await save(win, prefix + "_consolidate.png");
    }

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
    await save(win, prefix + "_correction.png");

    let trained = null;
    if (lang === "en") {
      const jobId = await js(win, `
        (async () => {
          const button = document.querySelector("[data-confirm-correction]");
          if (!button) return "";
          button.click();
          for (let i = 0; i < 40; i += 1) {
            if (document.querySelector(".constellation")) return (state.job && state.job.id) || "open";
            await new Promise((r) => setTimeout(r, 200));
          }
          return "";
        })()
      `);
      if (!jobId) throw new Error("没有进入巩固");
      trained = await js(win, `
        (async () => {
          for (let i = 0; i < 180; i += 1) {
            const job = state.job;
            const curve = job && (job.loss_curve || []);
            if (curve.length >= 1) return { epoch: curve[0].epoch, loss: curve[0].loss, id: job.id };
            await new Promise((r) => setTimeout(r, 2000));
          }
          return null;
        })()
      `);
      if (!trained) throw new Error("训练没有打出第一轮 loss");
      await save(win, prefix + "_consolidate.png");
      await js(win, `fetch("/api/jobs/" + ${JSON.stringify(trained.id)} + "/cancel", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" })`);
    }

    console.log("I18N_SHOTS", JSON.stringify({ lang, ready, recall, proposal: proposal.slice(0, 120), trained, errors: errors.filter((line) => /SyntaxError|nebula|UnrealBloom|shader/i.test(line)).slice(0, 6) }));
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

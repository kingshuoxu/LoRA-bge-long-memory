/**
 * 用真实后端和 Electron 窗口截四张设计图：对话、巩固训练中、星云、纠正确认。
 * 依赖验收目录里已经训好的专家。不访问外网。
 */
const { app, BrowserWindow } = require("electron");
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

const python = process.env.LORA_MEMORY_PYTHON || path.join(__dirname, "..", ".venv", "bin", "python");
const home = process.env.LORA_MEMORY_HOME;
const models = process.env.LORA_MEMORY_MODELS || path.join(__dirname, "..", "models");
const dirs = [
  process.env.SHOT_DIR,
  "/cursor/stores/self/artifacts",
  "/opt/cursor/artifacts/screenshots",
].filter(Boolean);

app.commandLine.appendSwitch("no-sandbox");
app.commandLine.appendSwitch("use-gl", "angle");
app.commandLine.appendSwitch("use-angle", "swiftshader");
app.commandLine.appendSwitch("enable-webgl");
app.commandLine.appendSwitch("ignore-gpu-blocklist");

function save(win, name) {
  return win.capturePage().then((image) => {
    const png = image.toPNG();
    dirs.forEach((dir) => {
      fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(path.join(dir, name), png);
    });
  });
}

function waitReady(child) {
  return new Promise((resolve, reject) => {
    let buffer = "";
    const timer = setTimeout(() => reject(new Error("后端启动超时")), 90000);
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

async function sleep(ms) {
  await new Promise((resolve) => setTimeout(resolve, ms));
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
  try {
    const port = await waitReady(backend);
    const win = new BrowserWindow({
      show: true,
      width: 1440,
      height: 900,
      backgroundColor: "#070910",
      webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: false },
    });
    await win.loadURL(`http://127.0.0.1:${port}/`);
    const ready = async () => win.webContents.executeJavaScript(`
      (async () => {
        for (let i = 0; i < 60; i += 1) {
          const app = document.getElementById("app");
          if (app && !app.hidden) return true;
          await new Promise((r) => setTimeout(r, 500));
        }
        return false;
      })()
    `);
    if (!await ready()) throw new Error("界面没有就绪");
    const openConv = async (convId) => {
      const opened = await win.webContents.executeJavaScript(`
        (async () => {
          const id = ${JSON.stringify(convId)};
          for (let i = 0; i < 40; i += 1) {
            const button = [...document.querySelectorAll("[data-open]")].find((item) => item.dataset.open === id);
            if (button) { button.click(); return true; }
            await new Promise((r) => setTimeout(r, 250));
          }
          return false;
        })()
      `);
      if (!opened) throw new Error("没有打开对话 " + convId);
      await sleep(700);
    };
    const chatId = await win.webContents.executeJavaScript(`
      (async () => {
        const conv = await fetch("/api/conversations", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }).then((r) => r.json());
        const sent = await fetch("/api/conversations/" + conv.id + "/messages", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content: "沈星河的猫的名字是什么？" }),
        }).then((r) => r.json());
        if (!sent.assistant || !String(sent.assistant.content).includes("暮雪")) {
          throw new Error("对话没有回答暮雪：" + JSON.stringify(sent.assistant));
        }
        return conv.id;
      })()
    `);
    await win.webContents.reload();
    if (!await ready()) throw new Error("刷新后界面没有就绪");
    await openConv(chatId);
    await save(win, "screenshot_chat.png");

    await win.webContents.executeJavaScript(`document.getElementById("nav-nebula").click()`);
    await sleep(2500);
    await save(win, "screenshot_nebula.png");

    const proposal = await win.webContents.executeJavaScript(`
      (async () => {
        const conv = await fetch("/api/conversations", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }).then((r) => r.json());
        const sent = await fetch("/api/conversations/" + conv.id + "/messages", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content: "沈星河的住址不是青岚镇，是星港。" }),
        }).then((r) => r.json());
        if (!sent.proposal || sent.proposal.new_value !== "星港") {
          throw new Error("没有生成住址纠正：" + JSON.stringify(sent.proposal));
        }
        return { proposal: sent.proposal, id: conv.id };
      })()
    `);
    await win.webContents.reload();
    if (!await ready()) throw new Error("纠正界面没有就绪");
    await openConv(proposal.id);
    await save(win, "screenshot_correction.png");

    const jobId = await win.webContents.executeJavaScript(`
      fetch("/api/corrections/commit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ proposal: ${JSON.stringify(proposal.proposal)}, conversation_id: ${JSON.stringify(proposal.id)} }),
      }).then((r) => r.json()).then((data) => data.job && data.job.id)
    `);
    if (!jobId) throw new Error("没有开始纠正训练");
    const seen = await win.webContents.executeJavaScript(`
      (async () => {
        for (let i = 0; i < 180; i += 1) {
          const job = await fetch("/api/jobs/${jobId}").then((r) => r.json());
          const curve = job.loss_curve || [];
          if (curve.length >= 1) return job.phase + ":" + curve.length;
          if (job.status === "failed") throw new Error(job.error || "训练失败");
          await new Promise((r) => setTimeout(r, 2000));
        }
        throw new Error("训练没有进入第一轮");
      })()
    `);
    await win.webContents.reload();
    if (!await ready()) throw new Error("训练界面没有就绪");
    await win.webContents.executeJavaScript(`document.getElementById("nav-consolidate").click()`);
    await sleep(900);
    await save(win, "screenshot_consolidate_training.png");
    await win.webContents.executeJavaScript(`fetch("/api/jobs/${jobId}/cancel", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" })`);
    console.log("SHOTS_OK", seen);
    backend.kill();
    app.exit(0);
  } catch (error) {
    console.error("SHOTS_FAIL", error);
    backend.kill();
    app.exit(1);
  }
}).catch((error) => {
  console.error("SHOTS_FAIL", error);
  app.exit(1);
});

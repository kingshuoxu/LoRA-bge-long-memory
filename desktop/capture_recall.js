/**
 * 截一张真实回忆：问句走后端路由，星云按返回的 trace 点亮对上的事实。
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
const question = "沈星河家的猫咪叫啥？";

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
    const ready = await win.webContents.executeJavaScript(`
      (async () => {
        for (let i = 0; i < 80; i += 1) {
          const app = document.getElementById("app");
          if (app && !app.hidden && document.getElementById("nebula-canvas")) return true;
          await new Promise((r) => setTimeout(r, 500));
        }
        return false;
      })()
    `);
    if (!ready) throw new Error("界面没有就绪");
    await win.webContents.executeJavaScript(`
      (async () => {
        document.getElementById("new-chat").click();
        for (let i = 0; i < 40; i += 1) {
          const empty = document.querySelector("#messages .empty");
          if (empty) return true;
          await new Promise((r) => setTimeout(r, 200));
        }
        return false;
      })()
    `);
    await win.webContents.executeJavaScript(`
      (() => {
        const input = document.getElementById("input");
        input.value = ${JSON.stringify(question)};
        document.getElementById("composer").requestSubmit();
        return true;
      })()
    `);
    const seen = await win.webContents.executeJavaScript(`
      (async () => {
        let last = "";
        let stable = 0;
        for (let i = 0; i < 120; i += 1) {
          const chip = document.querySelector(".recall-chip");
          const body = document.querySelector(".bubble.assistant .body");
          const banner = document.getElementById("recall-banner");
          const text = body ? body.textContent : "";
          if (chip && banner && !banner.hidden && text && text === last) stable += 1;
          else stable = 0;
          last = text;
          if (chip && stable >= 3) {
            return {
              chip: chip.textContent,
              banner: banner.textContent,
              answer: text,
              idle: chip.classList.contains("idle"),
            };
          }
          await new Promise((r) => setTimeout(r, 400));
        }
        return null;
      })()
    `);
    if (!seen) throw new Error("没有等到回忆标记");
    if (seen.idle || !seen.chip.includes("暮雪")) {
      throw new Error(`回忆标记不对 ${JSON.stringify(seen)}`);
    }
    await win.webContents.executeJavaScript(`
      (() => {
        const trace = state.recall;
        const fact = trace && trace.matched_facts && trace.matched_facts[0];
        if (!fact || !state.nebula) return false;
        const point = state.nebula.screenPoint(fact.node_id);
        const canvas = document.getElementById("nebula-canvas");
        const rect = canvas.getBoundingClientRect();
        if (!point) return false;
        canvas.dispatchEvent(new PointerEvent("pointermove", {
          clientX: rect.left + point.x,
          clientY: rect.top + point.y,
          bubbles: true,
        }));
        return true;
      })()
    `);
    await new Promise((resolve) => setTimeout(resolve, 600));
    await save(win, "screenshot_recall.png");
    console.log("RECALL_SHOT", JSON.stringify(seen));
    app.exit(0);
  } catch (error) {
    console.error("RECALL_SHOT_FAIL", error);
    app.exit(1);
  } finally {
    backend.kill("SIGTERM");
  }
}).catch((error) => {
  console.error("RECALL_SHOT_FAIL", error);
  app.exit(1);
});

const { app, BrowserWindow, dialog, ipcMain, Menu } = require("electron");
const { spawn, spawnSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");
const updater = require("./updater");

app.setName("lora-bge-memory");

let backend = null;
let mainWindow = null;

function exists(file) {
  try { return fs.existsSync(file); } catch (err) { return false; }
}

function findPython() {
  const candidates = [];
  if (process.env.LORA_MEMORY_PYTHON) candidates.push(process.env.LORA_MEMORY_PYTHON);
  if (process.resourcesPath) {
    candidates.push(path.join(process.resourcesPath, "runtime", "bin", "python3"));
    candidates.push(path.join(process.resourcesPath, "runtime", "python.exe"));
  }
  candidates.push(path.join(__dirname, "..", ".venv", "bin", "python"));
  candidates.push(path.join(__dirname, "..", ".venv", "Scripts", "python.exe"));
  for (const candidate of candidates) {
    if (exists(candidate)) return candidate;
  }
  return process.platform === "win32" ? "python" : "python3";
}

function findAppCode() {
  const packaged = path.join(process.resourcesPath || "", "app");
  if (exists(path.join(packaged, "memory_core", "__init__.py"))) return packaged;
  return path.resolve(__dirname, "..");
}

function findUi() {
  const packaged = path.join(process.resourcesPath || "", "ui");
  if (exists(path.join(packaged, "index.html"))) return packaged;
  return path.join(__dirname, "ui");
}

function waitForReady(child) {
  return new Promise((resolve, reject) => {
    let buffer = "";
    const timer = setTimeout(() => reject(new Error("后端启动超时")), 90000);
    const onData = (chunk) => {
      buffer += chunk.toString();
      const matched = buffer.match(/LORA_MEMORY_READY port=(\d+)/);
      if (matched) {
        clearTimeout(timer);
        resolve(Number(matched[1]));
      }
    };
    child.stdout.on("data", onData);
    child.stderr.on("data", (chunk) => { process.stderr.write(chunk); });
    child.on("exit", (code) => {
      clearTimeout(timer);
      reject(new Error(`后端退出 ${code}\n${buffer}`));
    });
  });
}

function memoryHome() {
  if (process.env.LORA_MEMORY_HOME) return process.env.LORA_MEMORY_HOME;
  if (app.isPackaged) return app.getPath("userData");
  if (process.platform === "win32") return path.join(process.env.APPDATA || "", "lora-bge-memory");
  if (process.platform === "darwin") return path.join(os.homedir(), "Library", "Application Support", "lora-bge-memory");
  return path.join(os.homedir(), ".local", "share", "lora-bge-memory");
}

function readLocale() {
  try {
    const data = JSON.parse(fs.readFileSync(path.join(memoryHome(), "settings.json"), "utf8"));
    return data.locale === "en" ? "en" : "zh-CN";
  } catch (err) {
    return "zh-CN";
  }
}

let menuLocale = "";

function installMenu() {
  const locale = readLocale();
  if (locale === menuLocale && Menu.getApplicationMenu()) return;
  menuLocale = locale;
  const en = locale === "en";
  const template = [
    {
      label: en ? "File" : "文件",
      submenu: [{ role: "quit", label: en ? "Quit" : "退出" }],
    },
    {
      label: en ? "Edit" : "编辑",
      submenu: [
        { role: "undo", label: en ? "Undo" : "撤销" },
        { role: "redo", label: en ? "Redo" : "重做" },
        { type: "separator" },
        { role: "cut", label: en ? "Cut" : "剪切" },
        { role: "copy", label: en ? "Copy" : "复制" },
        { role: "paste", label: en ? "Paste" : "粘贴" },
        { role: "selectAll", label: en ? "Select All" : "全选" },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
  if (mainWindow) mainWindow.setTitle(en ? "LoRA Long Memory" : "LoRA 长记忆");
}

async function createWindow(port) {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1100,
    minHeight: 700,
    title: readLocale() === "en" ? "LoRA Long Memory" : "LoRA 长记忆",
    backgroundColor: "#070910",
    icon: path.join(findUi(), "icon.png"),
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, "preload.js"),
    },
  });
  await mainWindow.loadURL(`http://127.0.0.1:${port}/`);
  if (process.env.LORA_MEMORY_SCREENSHOT) {
    setTimeout(async () => {
      try {
        const image = await mainWindow.capturePage();
        fs.writeFileSync(process.env.LORA_MEMORY_SCREENSHOT, image.toPNG());
        if (process.env.LORA_MEMORY_EXIT_AFTER_SHOT === "1") app.exit(0);
      } catch (err) {
        console.error(err);
      }
    }, 2500);
  }
}

function stopBackend() {
  if (backend && !backend.killed) {
    try { backend.kill(); } catch (err) { /* 进程已经退出 */ }
  }
}

function packagedEnv(env) {
  if (!app.isPackaged) return env;
  const home = app.getPath("userData");
  return {
    ...env,
    LORA_MEMORY_HOME: home,
    LORA_MEMORY_MODELS: path.join(home, "models"),
    LORA_MEMORY_MIGRATE: "1",
  };
}

function stampUpgrade() {
  const home = app.getPath("userData");
  const marker = fs.readFileSync(path.join(home, "conversations.sqlite"));
  if (!marker.includes(Buffer.from("UPGRADE_KEEP"))) {
    console.error("UPGRADE_STAMP missing marker");
    app.exit(2);
    return;
  }
  const sentinel = path.join(home, "models", "sentinel.txt");
  if (!fs.existsSync(sentinel) || fs.readFileSync(sentinel, "utf8").trim() !== "keep") {
    console.error("UPGRADE_STAMP missing sentinel");
    app.exit(3);
    return;
  }
  const models = path.join(home, "models");
  const qwen = path.join(models, "Qwen2.5-0.5B-Instruct", "model.safetensors");
  let modelsChecked = false;
  let modelsReady = false;
  if (exists(qwen) && fs.statSync(qwen).size >= 500_000_000) {
    modelsChecked = true;
    const result = spawnSync(findPython(), ["-c", [
      "from memory_core.models_mgr import ensure_models",
      "ensure_models(__import__('os').environ['LORA_MEMORY_MODELS'])",
      "print('MODELS_OK')",
    ].join("\n")], {
      encoding: "utf8",
      env: {
        ...process.env,
        PYTHONPATH: findAppCode(),
        LORA_MEMORY_MODELS: models,
        HF_HUB_OFFLINE: "1",
        HF_HUB_DISABLE_TELEMETRY: "1",
        PYTHONUNBUFFERED: "1",
      },
    });
    if (result.status !== 0 || !String(result.stdout || "").includes("MODELS_OK")) {
      console.error(result.stdout || "", result.stderr || "");
      app.exit(4);
      return;
    }
    modelsReady = true;
  }
  fs.writeFileSync(path.join(home, "upgrade-stamp.json"), JSON.stringify({
    version: app.getVersion(),
    modelsChecked,
    modelsReady,
  }));
  console.log("UPGRADE_STAMP_OK", app.getVersion());
  app.exit(0);
}

ipcMain.handle("update:get", () => updater.state());
ipcMain.handle("update:check", () => updater.checkForUpdates());
ipcMain.handle("update:install", () => updater.installUpdate());

app.on("before-quit", stopBackend);
app.on("window-all-closed", () => {
  stopBackend();
  if (process.platform !== "darwin") app.quit();
});

app.whenReady().then(async () => {
  const smoke = process.argv.includes("--upgrade-smoke");
  if (process.env.LORA_MEMORY_UPGRADE_STAMP === "1" && !smoke) {
    stampUpgrade();
    return;
  }
  if (smoke) {
    const timer = setTimeout(() => {
      console.error("UPGRADE_SMOKE timeout");
      app.exit(1);
    }, 180000);
    await updater.runUpgradeSmoke();
    clearTimeout(timer);
    return;
  }
  installMenu();
  setInterval(installMenu, 1000);
  const python = findPython();
  const appCode = findAppCode();
  const ui = findUi();
  if (process.argv.includes("--e2e-check")) {
    const child = spawn(python, ["-m", "memory_core.e2e_check"], {
      cwd: appCode,
      env: { ...process.env, PYTHONPATH: appCode, PYTHONUNBUFFERED: "1", LORA_MEMORY_UI: ui },
      stdio: "inherit",
    });
    child.on("exit", (code) => app.exit(code == null ? 1 : code));
    return;
  }
  const env = packagedEnv({
    ...process.env,
    PYTHONPATH: appCode,
    PYTHONUNBUFFERED: "1",
    LORA_MEMORY_UI: ui,
    HF_HUB_DISABLE_TELEMETRY: "1",
  });
  if (process.platform === "linux" && process.resourcesPath) {
    const libDir = path.join(process.resourcesPath, "runtime", "lib");
    if (exists(libDir)) {
      env.LD_LIBRARY_PATH = env.LD_LIBRARY_PATH ? `${libDir}:${env.LD_LIBRARY_PATH}` : libDir;
    }
  }
  backend = spawn(python, ["-m", "backend.server"], { cwd: appCode, env });
  try {
    const port = await waitForReady(backend);
    await createWindow(port);
    updater.attach(mainWindow);
    if (app.isPackaged) {
      setTimeout(() => updater.checkForUpdates().catch((err) => console.error(err)), 4000);
    }
  } catch (err) {
    dialog.showErrorBox("LoRA 长记忆", String(err && err.message ? err.message : err));
    app.exit(1);
  }
  }).catch((err) => {
  dialog.showErrorBox("LoRA 长记忆", String(err && err.message ? err.message : err));
  app.exit(1);
});

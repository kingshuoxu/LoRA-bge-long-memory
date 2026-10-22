const { app, BrowserWindow, dialog, Menu } = require("electron");
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

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

function installMenu() {
  const template = [
    {
      label: "文件",
      submenu: [{ role: "quit", label: "退出" }],
    },
    {
      label: "编辑",
      submenu: [
        { role: "undo", label: "撤销" },
        { role: "redo", label: "重做" },
        { type: "separator" },
        { role: "cut", label: "剪切" },
        { role: "copy", label: "复制" },
        { role: "paste", label: "粘贴" },
        { role: "selectAll", label: "全选" },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

async function createWindow(port) {
  mainWindow = new BrowserWindow({
    width: 1100,
    height: 760,
    minWidth: 800,
    minHeight: 560,
    title: "LoRA 长记忆",
    backgroundColor: "#f3efe6",
    webPreferences: { contextIsolation: true, nodeIntegration: false },
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

app.on("before-quit", stopBackend);
app.on("window-all-closed", () => {
  stopBackend();
  if (process.platform !== "darwin") app.quit();
});

app.whenReady().then(async () => {
  installMenu();
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
  const env = {
    ...process.env,
    PYTHONPATH: appCode,
    PYTHONUNBUFFERED: "1",
    LORA_MEMORY_UI: ui,
    HF_HUB_DISABLE_TELEMETRY: "1",
  };
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
  } catch (err) {
    dialog.showErrorBox("LoRA 长记忆", String(err && err.message ? err.message : err));
    app.exit(1);
  }
  }).catch((err) => {
  dialog.showErrorBox("LoRA 长记忆", String(err && err.message ? err.message : err));
  app.exit(1);
});

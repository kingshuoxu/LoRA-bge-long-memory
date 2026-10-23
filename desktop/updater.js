"use strict";

const { app, shell } = require("electron");
const fs = require("fs");
const http = require("http");
const https = require("https");
const path = require("path");
const { autoUpdater } = require("electron-updater");
const { downloadVerified } = require("./download-file");
const plan = require("./update-plan");

autoUpdater.autoDownload = false;
autoUpdater.autoInstallOnAppQuit = false;
autoUpdater.logger = console;

let mainWindow = null;
let state = {
  status: "idle",
  mode: "dev",
  version: "",
  current: "",
  notes: "",
  percent: 0,
  url: "",
  file: "",
  mirror: "",
  error: "",
};
let checking = null;
let suppressUpdaterError = false;

function dataHome() {
  return app.getPath("userData");
}

function readMirror() {
  try {
    const data = JSON.parse(fs.readFileSync(path.join(dataHome(), "settings.json"), "utf8"));
    return plan.normalizeMirror(data.update_url || "");
  } catch (err) {
    return "";
  }
}

function currentMode() {
  return plan.installMode({
    packaged: app.isPackaged,
    platform: process.platform,
    appImage: Boolean(process.env.APPIMAGE),
  });
}

function revealDownload(file) {
  if (!file || !fs.existsSync(file)) return;
  if (process.platform === "darwin") shell.showItemInFolder(file);
  else shell.openPath(file);
}

function publish(partial) {
  state = { ...state, ...partial, mode: currentMode(), current: app.getVersion(), mirror: readMirror() };
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("update:state", state);
  }
  return state;
}

function requestJson(url) {
  return new Promise((resolve, reject) => {
    const lib = url.startsWith("http:") ? http : https;
    const req = lib.get(url, {
      headers: {
        Accept: "application/vnd.github+json",
        "User-Agent": "lora-bge-memory",
      },
    }, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        res.resume();
        requestJson(new URL(res.headers.location, url).href).then(resolve, reject);
        return;
      }
      const chunks = [];
      res.on("data", (chunk) => chunks.push(chunk));
      res.on("end", () => {
        const body = Buffer.concat(chunks).toString("utf8");
        if (res.statusCode !== 200) {
          reject(new Error(`HTTP ${res.statusCode}`));
          return;
        }
        try {
          resolve(JSON.parse(body));
        } catch (err) {
          reject(err);
        }
      });
    });
    req.setTimeout(12000, () => {
      req.destroy(new Error("更新检查超时"));
    });
    req.on("error", reject);
  });
}

function withTimeout(promise, ms, label) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(label || "超时")), ms);
    Promise.resolve(promise).then((value) => {
      clearTimeout(timer);
      resolve(value);
    }, (err) => {
      clearTimeout(timer);
      reject(err);
    });
  });
}

async function latestRelease() {
  const url = `https://api.github.com/repos/${plan.GITHUB_OWNER}/${plan.GITHUB_REPO}/releases?per_page=30`;
  const releases = await requestJson(url);
  return plan.newestDesktopRelease(releases);
}

async function manualFromBase(base, mode) {
  const manifest = await requestJson(new URL("desktop-release.json", base).href);
  const version = String(manifest.version || "");
  if (!version || plan.compareVersions(version, app.getVersion()) <= 0) return null;
  const files = Array.isArray(manifest.files) ? manifest.files : [];
  const asset = plan.pickAsset(files.map((item) => ({
    name: item.name,
    url: new URL(item.url || item.name, base).href,
    sha256: item.sha256,
  })), mode, process.arch);
  if (!asset) return null;
  return {
    version,
    notes: plan.notesText(manifest.notes),
    url: asset.url,
    name: asset.name,
    sha256: String(asset.sha256 || "").toLowerCase(),
  };
}

async function deliverManual(info) {
  const dest = path.join(dataHome(), "updates", info.name);
  publish({
    status: "downloading",
    version: info.version,
    notes: info.notes,
    url: info.url,
    percent: 0,
    error: "",
  });
  let lastError = null;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      await downloadVerified(info.url, dest, info.sha256, (got, total) => {
        publish({ status: "downloading", percent: total ? Math.round((got / total) * 100) : 0 });
      });
      lastError = null;
      break;
    } catch (err) {
      lastError = err;
    }
  }
  if (lastError) throw lastError;
  publish({ status: "manual", version: info.version, notes: info.notes, url: info.url, file: dest, percent: 100 });
  revealDownload(dest);
}

function bindAutoUpdater() {
  autoUpdater.removeAllListeners();
  autoUpdater.on("update-available", (info) => {
    publish({
      status: "available",
      version: info.version,
      notes: plan.notesText(info.releaseNotes),
      error: "",
    });
  });
  autoUpdater.on("download-progress", (progress) => {
    publish({ status: "downloading", percent: Math.round(progress.percent || 0) });
  });
  autoUpdater.on("update-downloaded", (info) => {
    publish({
      status: "downloaded",
      version: info.version,
      notes: plan.notesText(info.releaseNotes) || state.notes,
      percent: 100,
      error: "",
    });
  });
  autoUpdater.on("error", (err) => {
    if (suppressUpdaterError) return;
    publish({ status: "error", error: String(err && err.message ? err.message : err) });
  });
}

function downloadWithStall(result, ms) {
  if (!result || !result.downloadPromise) return Promise.resolve();
  return new Promise((resolve, reject) => {
    let timer = null;
    const fail = () => {
      if (result.cancellationToken) result.cancellationToken.cancel();
      reject(new Error("下载没有进展"));
    };
    const bump = () => {
      clearTimeout(timer);
      timer = setTimeout(fail, ms);
    };
    bump();
    autoUpdater.on("download-progress", bump);
    result.downloadPromise.then((value) => {
      clearTimeout(timer);
      autoUpdater.removeListener("download-progress", bump);
      resolve(value);
    }, (err) => {
      clearTimeout(timer);
      autoUpdater.removeListener("download-progress", bump);
      reject(err);
    });
  });
}

async function checkAutomatic(urls) {
  bindAutoUpdater();
  autoUpdater.autoDownload = true;
  autoUpdater.disableDifferentialDownload = false;
  let lastError = null;
  suppressUpdaterError = true;
  try {
    for (const url of urls) {
      try {
        autoUpdater.setFeedURL({ provider: "generic", url });
        const result = await withTimeout(autoUpdater.checkForUpdates(), 12000, "更新地址超时");
        if (!result || !result.updateInfo || result.isUpdateAvailable === false) {
          publish({ status: "current", version: app.getVersion(), error: "" });
          return state;
        }
        if (plan.compareVersions(result.updateInfo.version, app.getVersion()) <= 0) {
          publish({ status: "current", version: app.getVersion(), notes: "", error: "" });
          return state;
        }
        await downloadWithStall(result, 30000);
        return state;
      } catch (err) {
        lastError = err;
      }
    }
  } finally {
    suppressUpdaterError = false;
  }
  throw lastError || new Error("没有可用的更新地址");
}

async function checkManual(mirror) {
  const bases = [];
  try {
    const release = await latestRelease();
    if (release && plan.compareVersions(release.version, app.getVersion()) > 0) {
      bases.push(plan.githubDownloadBase(release.tag));
    } else if (release) {
      publish({ status: "current", version: app.getVersion(), error: "" });
      return state;
    }
  } catch (err) {
    if (!mirror) throw err;
  }
  if (mirror) bases.push(mirror);
  if (!bases.length) {
    publish({ status: "current", version: app.getVersion(), error: "" });
    return state;
  }
  let lastError = null;
  for (const base of bases) {
    try {
      const info = await manualFromBase(base, currentMode());
      if (!info) {
        publish({ status: "current", version: app.getVersion(), error: "" });
        return state;
      }
      await deliverManual(info);
      return state;
    } catch (err) {
      lastError = err;
    }
  }
  throw lastError || new Error("没有可用的更新地址");
}

async function checkForUpdates() {
  if (checking) return checking;
  checking = (async () => {
    const mode = currentMode();
    publish({ status: "checking", error: "", percent: 0 });
    if (mode === "dev") {
      publish({ status: "dev", error: "" });
      return state;
    }
    const mirror = readMirror() || plan.normalizeMirror(process.env.LORA_MEMORY_UPDATE_URL || "");
    try {
      if (mode === "appimage" || mode === "nsis") {
        let release = null;
        try {
          release = await latestRelease();
        } catch (err) {
          if (!mirror) throw err;
        }
        const urls = plan.feedUrls(mirror, release);
        if (!urls.length) throw new Error("没有可用的更新地址");
        await checkAutomatic(urls);
      } else {
        await checkManual(mirror);
      }
    } catch (err) {
      publish({ status: "error", error: String(err && err.message ? err.message : err) });
    }
    return state;
  })().finally(() => {
    checking = null;
  });
  return checking;
}

function installUpdate() {
  if (state.status === "downloaded" && (state.mode === "appimage" || state.mode === "nsis")) {
    setImmediate(() => autoUpdater.quitAndInstall(false, true));
    return state;
  }
  if (state.file && fs.existsSync(state.file)) {
    revealDownload(state.file);
    return state;
  }
  if (state.url) shell.openExternal(state.url);
  return state;
}

function attach(window) {
  mainWindow = window;
  publish({});
}

async function runUpgradeSmoke() {
  const feed = plan.normalizeMirror(process.env.LORA_MEMORY_UPDATE_URL || "");
  if (!feed) {
    console.error("UPGRADE_SMOKE missing feed");
    app.exit(1);
    return;
  }
  try {
    bindAutoUpdater();
    autoUpdater.autoDownload = true;
    autoUpdater.disableDifferentialDownload = true;
    autoUpdater.setFeedURL({ provider: "generic", url: feed });
    const result = await autoUpdater.checkForUpdates();
    if (!result || !result.updateInfo || plan.compareVersions(result.updateInfo.version, app.getVersion()) <= 0) {
      console.error("UPGRADE_SMOKE no update", result && result.updateInfo);
      app.exit(1);
      return;
    }
    if (result.downloadPromise) await result.downloadPromise;
    console.log("UPGRADE_SMOKE downloaded", result.updateInfo.version);
    // 正式安装走 quitAndInstall(false, true)，会换掉 AppImage 再拉起新进程。
    // 验收机器上新进程没有 --no-sandbox 起不来，所以只在这一步加上启动参数。
    // quitAndInstall 会吞掉 doInstall 的异常，所以用 smokeInstallError 把失败带出来。
    let smokeInstallError = null;
    const original = autoUpdater.constructor.prototype.doInstall;
    autoUpdater.constructor.prototype.doInstall = function smokeInstall(options) {
      try {
        if (!options.isForceRunAfter) return original.call(this, options);
        const { execFileSync, spawnSync } = require("child_process");
        const appImageFile = process.env.APPIMAGE;
        const installerPath = this.installerPath;
        if (!appImageFile || !installerPath) {
          throw new Error("APPIMAGE 或更新包不在");
        }
        fs.unlinkSync(appImageFile);
        const base = path.basename(appImageFile);
        const destination = /\d+\.\d+\.\d+/.test(base)
          ? path.join(path.dirname(appImageFile), path.basename(installerPath))
          : appImageFile;
        execFileSync("mv", ["-f", installerPath, destination]);
        const child = spawnSync(destination, ["--no-sandbox", "--disable-gpu"], {
          env: { ...process.env, APPIMAGE_SILENT_INSTALL: "true" },
          stdio: "inherit",
        });
        if (child.status !== 0) {
          throw new Error(`升级后的进程退出 ${child.status}`);
        }
        return true;
      } catch (err) {
        smokeInstallError = err;
        throw err;
      }
    };
    autoUpdater.quitAndInstall(false, true);
    if (smokeInstallError) throw smokeInstallError;
    app.exit(0);
  } catch (err) {
    console.error("UPGRADE_SMOKE", err);
    app.exit(1);
  }
}

module.exports = {
  attach,
  checkForUpdates,
  installUpdate,
  publish,
  state: () => state,
  runUpgradeSmoke,
  currentMode,
};

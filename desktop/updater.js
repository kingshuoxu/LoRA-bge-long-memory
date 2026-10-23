"use strict";

const { app, shell } = require("electron");
const { spawnSync } = require("child_process");
const fs = require("fs");
const http = require("http");
const https = require("https");
const path = require("path");
const { autoUpdater } = require("electron-updater");
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

function macSigned() {
  if (process.platform !== "darwin") return false;
  const result = spawnSync("codesign", ["-dv", "--verbose=2", process.execPath], { encoding: "utf8" });
  const text = `${result.stdout || ""}\n${result.stderr || ""}`;
  // 临时签名（adhoc）没有 Developer ID，Squirrel 不会收。
  return /Authority=Developer ID Application:/.test(text);
}

function currentMode() {
  return plan.installMode({
    packaged: app.isPackaged,
    platform: process.platform,
    appImage: Boolean(process.env.APPIMAGE),
    macSigned: macSigned(),
  });
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

function downloadFile(url, dest, onProgress) {
  return new Promise((resolve, reject) => {
    const lib = url.startsWith("http:") ? http : https;
    const req = lib.get(url, { headers: { "User-Agent": "lora-bge-memory" } }, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        res.resume();
        downloadFile(new URL(res.headers.location, url).href, dest, onProgress).then(resolve, reject);
        return;
      }
      if (res.statusCode !== 200) {
        res.resume();
        reject(new Error(`HTTP ${res.statusCode}`));
        return;
      }
      const total = Number(res.headers["content-length"] || 0);
      let got = 0;
      fs.mkdirSync(path.dirname(dest), { recursive: true });
      const file = fs.createWriteStream(dest);
      res.on("data", (chunk) => {
        got += chunk.length;
        if (onProgress) onProgress(got, total);
      });
      res.pipe(file);
      file.on("finish", () => file.close(() => resolve(dest)));
      file.on("error", reject);
    });
    req.on("error", reject);
  });
}

function manualCopy(release, mode) {
  const asset = plan.pickAsset(release.assets, mode, process.arch);
  if (!asset) return null;
  return {
    version: release.version,
    notes: release.notes,
    url: asset.browser_download_url || asset.url || "",
    name: asset.name || path.basename(asset.url || "update.bin"),
  };
}

async function manualFromMirror(mirror, mode) {
  const manifest = await requestJson(new URL("desktop-release.json", mirror).href);
  const version = String(manifest.version || "");
  if (!version || plan.compareVersions(version, app.getVersion()) <= 0) return null;
  const files = Array.isArray(manifest.files) ? manifest.files : [];
  const asset = plan.pickAsset(files.map((item) => ({
    name: item.name,
    url: new URL(item.url || item.name, mirror).href,
  })), mode, process.arch);
  if (!asset) return null;
  return {
    version,
    notes: plan.notesText(manifest.notes),
    url: asset.url,
    name: asset.name,
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
  await downloadFile(info.url, dest, (got, total) => {
    publish({ status: "downloading", percent: total ? Math.round((got / total) * 100) : 0 });
  });
  publish({ status: "manual", version: info.version, notes: info.notes, url: info.url, file: dest, percent: 100 });
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
  let info = null;
  let mirrorError = null;
  if (mirror) {
    try {
      info = await manualFromMirror(mirror, currentMode());
    } catch (err) {
      mirrorError = err;
    }
  }
  if (!info) {
    try {
      const release = await latestRelease();
      if (release && plan.compareVersions(release.version, app.getVersion()) > 0) {
        info = manualCopy(release, currentMode());
      }
    } catch (err) {
      if (!info) throw mirrorError || err;
    }
  }
  if (!info) {
    publish({ status: "current", version: app.getVersion(), error: "" });
    return state;
  }
  await deliverManual(info);
  return state;
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
      if (mode === "appimage" || mode === "nsis" || mode === "mac-auto") {
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
  if (state.status === "downloaded" && (state.mode === "appimage" || state.mode === "nsis" || state.mode === "mac-auto")) {
    setImmediate(() => autoUpdater.quitAndInstall(false, true));
    return state;
  }
  if (state.file && fs.existsSync(state.file)) {
    shell.openPath(state.file);
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
    autoUpdater.quitAndInstall(true, false);
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

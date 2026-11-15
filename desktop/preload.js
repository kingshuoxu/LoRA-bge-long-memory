"use strict";

const { contextBridge, ipcRenderer, webUtils } = require("electron");

contextBridge.exposeInMainWorld("desktop", {
  platform: process.platform,
  updateState() {
    return ipcRenderer.invoke("update:get");
  },
  checkForUpdates() {
    return ipcRenderer.invoke("update:check");
  },
  installUpdate() {
    return ipcRenderer.invoke("update:install");
  },
  onUpdateState(listener) {
    const wrapped = (_event, payload) => listener(payload);
    ipcRenderer.on("update:state", wrapped);
    return () => ipcRenderer.removeListener("update:state", wrapped);
  },
  pickDocument() {
    return ipcRenderer.invoke("docs:pick");
  },
  pathForFile(file) {
    try { return webUtils.getPathForFile(file); } catch (err) { return ""; }
  },
});

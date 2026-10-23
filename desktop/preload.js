"use strict";

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("desktop", {
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
});

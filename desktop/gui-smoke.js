/**
 * 打开真实界面，模型就绪之后巩固弹层和启动遮罩必须不可见。
 * 不下载模型：直接把 boot / app / modal 设成就绪时的 hidden 状态，再读计算样式。
 * author CSS 里的 display:grid 如果盖过 HTML hidden，这里会失败。
 */
const { app, BrowserWindow } = require("electron");
const path = require("path");

app.commandLine.appendSwitch("no-sandbox");
app.commandLine.appendSwitch("disable-gpu");
app.disableHardwareAcceleration();

const timer = setTimeout(() => {
  console.error("GUI_SMOKE_FAIL timeout");
  app.exit(1);
}, 30000);

function visibleSource() {
  return `(() => {
    const visible = (id) => {
      const el = document.getElementById(id);
      if (!el) return false;
      const style = getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
    };
    const before = { modal: visible("modal"), boot: visible("boot"), app: visible("app") };
    document.getElementById("boot").hidden = true;
    document.getElementById("app").hidden = false;
    document.getElementById("modal").hidden = true;
    const after = { modal: visible("modal"), boot: visible("boot"), app: visible("app") };
    document.getElementById("modal").hidden = false;
    const modalShown = visible("modal");
    document.getElementById("modal").hidden = true;
    const closed = !visible("modal");
    return { before, after, modalShown, closed };
  })()`;
}

app.whenReady().then(async () => {
  const win = new BrowserWindow({
    show: true,
    width: 1100,
    height: 800,
    webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: false },
  });
  win.webContents.on("console-message", () => {});
  await win.loadFile(path.join(__dirname, "ui", "index.html"));
  const result = await win.webContents.executeJavaScript(visibleSource());
  clearTimeout(timer);
  const fail = result.before.modal
    || !result.before.boot
    || result.after.modal
    || result.after.boot
    || !result.after.app
    || !result.modalShown
    || !result.closed;
  console.log(JSON.stringify(result));
  if (fail) {
    console.error("GUI_SMOKE_FAIL");
    app.exit(1);
    return;
  }
  console.log("GUI_SMOKE_OK");
  app.exit(0);
}).catch((error) => {
  console.error("GUI_SMOKE_FAIL", error);
  app.exit(1);
});

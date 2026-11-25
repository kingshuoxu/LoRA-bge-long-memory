// Real Electron window + production renderer, deterministic local HTTP responses.
// Run under Xvfb on Linux: node desktop/e2e/chat-experience.js
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const { _electron: electron } = require("playwright");

const desktop = path.resolve(__dirname, "..");
const packageBin = process.env.YINGYU_E2E_PACKAGED
  ? path.join(desktop, "dist", "linux-unpacked", "lora-bge-memory") : "";
const UI = packageBin ? path.join(path.dirname(packageBin), "resources", "ui") : path.join(desktop, "ui");
const evidence = path.join(desktop, "e2e-shots", "chat-experience");
const wait = () => {
  let release;
  const promise = new Promise((resolve) => { release = resolve; });
  return { promise, release };
};

async function fixture() {
  const heldReply = wait();
  const heldHistory = wait();
  const histories = {
    a: { id: "a", title: "Workshop notes", messages: Array.from({ length: 24 }, (_, i) => ({
      id: `old-${i}`, role: i % 2 ? "assistant" : "user",
      content: i % 2 ? "I can help put together a short agenda. What should we start with?" : "Help me prepare for the workshop.",
    })) },
    b: { id: "b", title: "Reading list", messages: [{ id: "read", role: "assistant", content: "Pick up the essay tomorrow." }] },
    c: { id: "c", title: "周末写作计划", messages: [
      { id: "cn-user", role: "user", content: "记住，我通常在周六上午写作。" },
      { id: "cn-reply", role: "assistant", content: "好的。你通常在周六上午写作，之后要调整的话，直接告诉我就行。" },
      { id: "cn-next", role: "user", content: "那就先留四十分钟，整理上周的笔记。" },
      { id: "cn-done", role: "assistant", content: "可以先挑出三条值得展开的想法，再给每条写一句摘要。" },
    ] },
  };
  const calls = [];
  let holdA = false;
  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, "http://127.0.0.1");
    const json = (body, status = 200) => {
      res.writeHead(status, { "Content-Type": "application/json" });
      res.end(JSON.stringify(body));
    };
    const endpoint = url.pathname.replace("/api/", "");
    if (endpoint === "health") return json({ device: "cpu", models: { state: "ready" } });
    if (endpoint === "settings") return json({ locale: "en" });
    if (endpoint === "conversations") return json({ conversations: Object.values(histories).map(({ messages, ...conv }) => conv) });
    if (endpoint === "conversations/a" && holdA) {
      holdA = false;
      calls.push({ history: "a" });
      await heldHistory.promise;
    }
    if (/^conversations\/[abc]$/.test(endpoint)) return json(histories[endpoint.at(-1)]);
    if (/^conversations\/[ab]\/messages$/.test(endpoint) && req.method === "POST") {
      const body = [];
      for await (const chunk of req) body.push(chunk);
      const { content } = JSON.parse(Buffer.concat(body));
      const id = endpoint.split("/")[1];
      calls.push({ id, content });
      if (content === "Too long") return json({ error: "Message rejected." }, 400);
      const user = { id: "new-request", role: "user", content };
      histories[id].messages.push(user);
      await heldReply.promise;
      const assistant = { id: "new-reply", role: "assistant", content: "We can start with a ten-minute discussion." };
      histories[id].messages.push(assistant);
      return json({ user, assistant });
    }
    if (url.pathname.startsWith("/api/")) return json({});
    const relative = url.pathname === "/" ? "index.html" : url.pathname.slice(1);
    const file = path.join(UI, relative);
    const types = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".png": "image/png", ".woff2": "font/woff2" };
    fs.readFile(file, (error, bytes) => {
      if (error) return res.writeHead(404).end();
      res.writeHead(200, { "Content-Type": types[path.extname(file)] || "application/octet-stream" });
      res.end(bytes);
    });
  });
  await new Promise((resolve, reject) => {
    server.on("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  return {
    url: `http://127.0.0.1:${server.address().port}/`, calls, heldReply, heldHistory,
    holdHistory: () => { holdA = true; },
    close: () => {
      heldReply.release();
      heldHistory.release();
      server.close();
      server.closeAllConnections();
    },
  };
}

async function main() {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), "yingyu-chat-ui-"));
  const server = await fixture();
  const bin = packageBin || require("electron");
  let app;
  try {
    const args = ["--no-sandbox", "--disable-gpu", `--user-data-dir=${home}`];
    if (!packageBin) args.unshift(desktop);
    app = await electron.launch({
      executablePath: bin, args, cwd: desktop,
      env: { ...process.env, LORA_MEMORY_HOME: home, LORA_MEMORY_PORT: "0", HF_HUB_OFFLINE: "1", TRANSFORMERS_OFFLINE: "1" },
    });
    const page = await app.firstWindow();
    page.setDefaultTimeout(12000);
    if (packageBin) assert.ok(await app.evaluate(({ app }) => app.isPackaged));
    await page.waitForURL(/^http:\/\/127\.0\.0\.1:\d+\//, { waitUntil: "load" });
    await page.goto(server.url, { waitUntil: "load" });
    const input = page.locator("#input");
    const send = page.locator("#send");
    const title = page.locator("#title");
    const active = (id) => page.locator(`[data-open="${id}"]`);
    const reply = page.getByText("We can start with a ten-minute discussion.", { exact: true });
    await page.locator("#app").waitFor();
    await page.locator(".bubble").first().waitFor();
    const win = await app.browserWindow(page);
    await win.evaluate((window) => window.setSize(1100, 700));
    await page.waitForFunction(() => innerWidth === 1100);
    const layout = await page.evaluate(() => {
      const messages = document.querySelector("#messages").getBoundingClientRect();
      const composer = document.querySelector("#composer").getBoundingClientRect();
      return { gap: composer.top - messages.bottom, messageHeight: messages.height, viewport: innerHeight };
    });
    assert.ok(layout.messageHeight > layout.viewport * 0.70, JSON.stringify(layout));
    assert.ok(layout.gap < 1, JSON.stringify(layout));
    assert.ok(await send.isDisabled());
    await page.evaluate(() => document.fonts.ready);
    assert.ok(await page.locator("#consolidate span").evaluate((el) => el.scrollWidth <= el.clientWidth));

    fs.mkdirSync(evidence, { recursive: true });
    await page.screenshot({ path: path.join(evidence, "01-chat-compact.png") });

    await input.focus();
    await input.evaluate((el) => el.addEventListener("keydown", (event) => {
      el.dataset.enterDuringComposition = JSON.stringify({ trusted: event.isTrusted, composing: event.isComposing });
    }, { once: true }));
    const cdp = await page.context().newCDPSession(page);
    await cdp.send("Input.imeSetComposition", { text: "nǐ hǎo", selectionStart: 6, selectionEnd: 6 });
    await page.keyboard.press("Enter");
    assert.deepEqual(JSON.parse(await input.getAttribute("data-enter-during-composition")), { trusted: true, composing: true });
    assert.equal(await page.locator("[data-pending-turn]").count(), 0, "IME confirmation must not submit");
    await cdp.send("Input.insertText", { text: "你好" });
    assert.match(await input.inputValue(), /你好/);
    // The injected composition does not include a native desktop candidate
    // window; Chromium may insert a newline for raw Enter. Test Shift+Enter
    // separately with already committed text.
    await input.fill("你好");
    await input.press("End");
    // Linux candidate selection can be reported as keyCode 229 instead.
    await input.dispatchEvent("keydown", { key: "Enter", keyCode: 229, bubbles: true, cancelable: true });
    assert.equal(await page.locator("[data-pending-turn]").count(), 0, "IME fallback key must not submit");
    await input.press("Shift+Enter");
    await page.keyboard.insertText("先检查布局。");
    assert.equal(await input.inputValue(), "你好\n先检查布局。");
    assert.equal(server.calls.length, 0);
    await input.press("Enter");
    await page.locator("[data-pending-turn]").waitFor();
    assert.equal(await page.locator("[data-pending-turn]").textContent(), "你好\n先检查布局。");
    await page.locator("#typing-status").waitFor();
    assert.equal(await page.locator("#typing-status").textContent(), "Generating a reply…");
    assert.ok(await send.isDisabled());
    await page.screenshot({ path: path.join(evidence, "02-generating.png") });

    await active("b").click();
    await page.getByText("Pick up the essay tomorrow.").waitFor();
    assert.ok(!await page.locator("[data-pending-turn]").count());
    assert.ok(!await page.locator("#typing").isVisible());
    await active("a").click();
    await page.locator("[data-user-message=new-request]").waitFor();
    assert.equal(await page.locator("[data-pending-turn]").count(), 0);
    assert.ok(await page.locator("#typing").isVisible());
    await active("b").click();
    await page.getByText("Pick up the essay tomorrow.").waitFor();
    await input.fill("Next draft");
    await active("b").focus();
    server.heldReply.release();
    await page.waitForFunction(() => !document.querySelector("#send").disabled);
    assert.equal(await title.textContent(), "Reading list");
    assert.equal(await input.inputValue(), "Next draft");
    assert.equal(await page.evaluate(() => document.activeElement.dataset.open), "b");
    assert.deepEqual(server.calls, [{ id: "a", content: "你好\n先检查布局。" }]);
    assert.ok(!await reply.count());

    server.holdHistory();
    const staleResponse = page.waitForResponse((response) => response.url().endsWith("/api/conversations/a"));
    await active("a").click();
    await active("b").click();
    await page.getByText("Pick up the essay tomorrow.").waitFor();
    server.heldHistory.release();
    await staleResponse;
    await page.evaluate(() => new Promise(requestAnimationFrame));
    assert.equal(await title.textContent(), "Reading list");
    assert.ok(!await reply.count());
    await active("a").click();
    await reply.waitFor();
    assert.equal(await page.locator(".bubble.user").last().textContent(), "你好\n先检查布局。");

    await input.fill("Too long");
    await input.press("Enter");
    await page.getByText("Message rejected.", { exact: true }).waitFor();
    assert.equal(await input.inputValue(), "Too long");
    assert.equal(await page.locator("[data-pending-turn]").count(), 0);
    assert.equal(server.calls.filter((call) => call.content === "Too long").length, 1);
    await page.emulateMedia({ reducedMotion: "reduce" });
    assert.equal(await send.evaluate((button) => getComputedStyle(button).transitionDuration), "0s");
    await win.evaluate((window) => window.setSize(1440, 900));
    await page.waitForFunction(() => innerWidth === 1440);
    await page.locator("#lang-zh").click();
    await active("c").click();
    await page.getByText("可以先挑出三条值得展开的想法，再给每条写一句摘要。").waitFor();
    await input.fill("先帮我列一个小提纲。");
    await input.focus();
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({ path: path.join(evidence, "03-chat-wide-zh.png") });
    console.log(`YINGYU_CHAT_EXPERIENCE_OK ${JSON.stringify(layout)}`);
  } finally {
    server.close();
    if (app) await app.close();
    fs.rmSync(home, { recursive: true, force: true });
  }
}
main().catch((error) => { console.error(error); process.exitCode = 1; });

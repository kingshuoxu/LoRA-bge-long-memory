// Real Linux packaged Electron / renderer, with isolated synthetic API data.
// Does not load model weights or train; this tests click-to-request binding.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const { _electron: electron } = require("playwright");

const desktop = path.resolve(__dirname, "..");
const binary = path.join(desktop, "dist", "linux-unpacked", "lora-bge-memory");
const packagedUi = path.join(path.dirname(binary), "resources", "ui");
const conversation = { id: "same-fact-chat", title: "Correction fixture" };
const proposals = ["Starport", "Newhaven"].map((value) => ({
  expert: "expert_fixture",
  fact_id: "shared-fact",
  old_statement: "Mira Chen lives in Qinglan.",
  new_statement: `Mira Chen lives in ${value}.`,
  new_value: value,
  source_text: `Mira Chen lives in ${value}, not Qinglan.`,
}));
const messages = proposals.flatMap((proposal, i) => [
  { id: `source-${i}`, role: "user", content: proposal.source_text },
  { id: `card-${i}`, role: "assistant", content: "Correction suggested.",
    extra: JSON.stringify({ kind: "correction_proposal", proposal }) },
]);

function log(message) {
  console.log(`[correction-cards] ${message}`);
}

async function bounded(label, ms, run) {
  let timer;
  try {
    return await Promise.race([
      Promise.resolve().then(run),
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error(`Timed out: ${label}`)), ms);
      }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

async function startFixture() {
  const requests = [];
  let rejectCommit = true;
  let releaseCommit;
  const held = new Promise((resolve) => { releaseCommit = resolve; });
  const responses = {
    "/api/settings": { locale: "en" },
    "/api/health": { device: "cpu", models: { state: "ready" } },
    "/api/conversations": { conversations: [conversation] },
    [`/api/conversations/${conversation.id}`]: { ...conversation, messages },
    "/api/nebula": { facts: [], experts: [], conversations: [] },
    "/api/pending": { pending: [] },
  };
  const types = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css",
    ".svg": "image/svg+xml", ".png": "image/png", ".woff2": "font/woff2" };
  const server = http.createServer((req, res) => {
    const pathname = new URL(req.url, "http://127.0.0.1").pathname;
    const json = (status, body) => {
      res.writeHead(status, { "Content-Type": "application/json" });
      res.end(JSON.stringify(body));
    };
    if (pathname === "/api/corrections/commit" && req.method === "POST") {
      let raw = "";
      req.setEncoding("utf8");
      req.on("data", (chunk) => { raw += chunk; });
      req.on("end", () => {
        try { requests.push(JSON.parse(raw)); }
        catch (error) { json(400, { error: "Invalid fixture request" }); return; }
        log(`observed correction POST #${requests.length}`);
        if (rejectCommit) {
          void held.then(() => json(409, { error: "Fixture: stale correction" }));
        } else {
          json(200, { job: { id: "fixture-job", status: "done" } });
        }
      });
      return;
    }
    if (pathname.startsWith("/api/")) {
      json(200, responses[pathname] || {});
      return;
    }
    const relative = pathname === "/" ? "index.html" : pathname.slice(1);
    if (!relative.split("/").every((part) => /^[\w.-]+$/.test(part) && part !== "..")) {
      res.writeHead(404).end();
      return;
    }
    const file = path.join(packagedUi, relative);
    fs.readFile(file, (error, bytes) => {
      if (error) { res.writeHead(404).end(); return; }
      if (relative === "index.html") log("served packaged index.html");
      res.writeHead(200, { "Content-Type": types[path.extname(file)] || "application/octet-stream" });
      res.end(bytes);
    });
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  return {
    url: `http://127.0.0.1:${server.address().port}/`,
    requests,
    releaseCommit,
    allowCommit: () => { rejectCommit = false; },
    close: () => {
      releaseCommit();
      server.close();
      server.closeAllConnections();
    },
  };
}

async function main() {
  fs.accessSync(binary, fs.constants.X_OK); // Deliberately no source fallback.
  fs.accessSync(path.join(packagedUi, "app.js"), fs.constants.R_OK);
  const home = fs.mkdtempSync(path.join(os.tmpdir(), "yingyu-card-e2e-"));
  let app;
  let fixture;
  let phase = "start fixture HTTP server";
  function next(label) {
    phase = label;
    log(label);
  }
  try {
    next(phase);
    fixture = await bounded("start fixture HTTP server", 5000, startFixture);
    next("launch packaged Electron");
    app = await electron.launch({
      executablePath: binary,
      args: ["--no-sandbox", "--disable-gpu", `--user-data-dir=${home}`],
      cwd: desktop,
      env: { ...process.env, LORA_MEMORY_HOME: home, LORA_MEMORY_PORT: "0", HF_HUB_OFFLINE: "1", TRANSFORMERS_OFFLINE: "1" },
      timeout: 120000,
    });
    next("wait for the first window");
    const page = await app.firstWindow({ timeout: 120000 });
    page.setDefaultTimeout(20000);
    page.setDefaultNavigationTimeout(20000);
    page.on("pageerror", (error) => console.error("[correction-cards] renderer error:", error));
    next("verify the executable is packaged");
    const packaged = await bounded("app.isPackaged", 10000,
      () => app.evaluate(({ app: electronApp }) => electronApp.isPackaged));
    assert.equal(packaged, true);
    const { requests } = fixture;
    next("navigate the packaged window to the isolated fixture");
    await bounded("start packaged window navigation", 10000, () =>
      app.evaluate(({ BrowserWindow }, url) => {
        const win = BrowserWindow.getAllWindows()[0];
        void win.loadURL(url).catch((error) => console.error(error));
      }, fixture.url));
    next("wait for both confirmation cards");
    const cards = proposals.map((_, i) => page.locator(`[data-msg="card-${i}"] [data-confirm-correction]`));
    for (let i = 0; i < cards.length; i++) {
      await cards[i].waitFor({ state: "visible" });
      const body = await page.locator(`[data-msg="card-${i}"] .proposal`).innerText();
      assert.ok(body.includes(proposals[i].new_statement));
    }
    assert.equal(page.url(), fixture.url);

    next("click the first card and check a duplicate click");
    await cards[0].click();
    await page.waitForFunction(() => document.querySelector('[data-msg="card-0"] button').disabled);
    // Simulate a redundant handler invocation while the original request is pending.
    await cards[0].evaluate((button) => { void button.onclick(); });
    fixture.releaseCommit();
    next("check stale-response handling and first request");
    await page.getByText("Fixture: stale correction", { exact: true }).waitFor();
    assert.deepEqual(requests, [{ proposal: proposals[0], conversation_id: conversation.id }]);
    assert.equal(await cards[0].isEnabled(), true);

    next("click the second card and check both requests");
    fixture.allowCommit();
    await cards[1].click();
    await page.locator("#consolidate-view").waitFor({ state: "visible" });
    assert.deepEqual(requests, proposals.map((proposal) => ({ proposal, conversation_id: conversation.id })));
    console.log("PACKAGED_CORRECTION_CARDS_OK: exact proposals and sources, stale error, duplicate suppression");
  } catch (error) {
    console.error(`[correction-cards] Failed at: ${phase}`, error);
    process.exitCode = 1;
  } finally {
    fixture?.close();
    if (app) {
      next("close Electron");
      try {
        await bounded("close Electron", 10000, () => app.close());
      } catch (error) {
        console.error("[correction-cards] Cleanup failed:", error);
        process.exitCode = 1;
        app.process().kill("SIGKILL");
        process.exit(1);
      }
    }
    fs.rmSync(home, { recursive: true, force: true });
    log("cleanup completed");
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });

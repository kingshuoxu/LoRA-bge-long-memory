// Real Linux packaged Electron / renderer, with isolated synthetic API data.
// Does not load model weights or train; this tests click-to-request binding.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { _electron: electron } = require("playwright");

const desktop = path.resolve(__dirname, "..");
const binary = path.join(desktop, "dist", "linux-unpacked", "lora-bge-memory");
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

async function main() {
  fs.accessSync(binary, fs.constants.X_OK); // Deliberately no source fallback.
  const home = fs.mkdtempSync(path.join(os.tmpdir(), "yingyu-card-e2e-"));
  let app;
  try {
    app = await electron.launch({
      executablePath: binary,
      args: ["--no-sandbox", "--disable-gpu", `--user-data-dir=${home}`],
      cwd: desktop,
      env: { ...process.env, LORA_MEMORY_HOME: home, LORA_MEMORY_PORT: "0", HF_HUB_OFFLINE: "1", TRANSFORMERS_OFFLINE: "1" },
      timeout: 120000,
    });
    const packaged = await app.evaluate(() => require("electron").app.isPackaged);
    assert.equal(packaged, true);
    const page = await app.firstWindow({ timeout: 120000 });
    page.setDefaultTimeout(30000);
    const requests = [];
    let rejectCommit = true;
    let releaseCommit;
    const held = new Promise((resolve) => { releaseCommit = resolve; });
    await page.route("**/api/**", async (route) => {
      const pathname = new URL(route.request().url()).pathname;
      const responses = {
        "/api/settings": { locale: "en" },
        "/api/health": { device: "cpu", models: { state: "ready" } },
        "/api/conversations": { conversations: [conversation] },
        [`/api/conversations/${conversation.id}`]: { ...conversation, messages },
        "/api/nebula": { facts: [], experts: [], conversations: [] },
        "/api/pending": { pending: [] },
      };
      if (pathname === "/api/corrections/commit") {
        assert.equal(route.request().method(), "POST");
        requests.push(route.request().postDataJSON());
        if (rejectCommit) {
          await held;
          return route.fulfill({ status: 409, json: { error: "Fixture: stale correction" } });
        }
        return route.fulfill({ json: { job: { id: "fixture-job", status: "done" } } });
      }
      return route.fulfill({ json: responses[pathname] || {} });
    });
    await page.reload();
    const cards = proposals.map((_, i) => page.locator(`[data-msg="card-${i}"] [data-confirm-correction]`));
    for (let i = 0; i < cards.length; i++) {
      await cards[i].waitFor({ state: "visible" });
      const body = await page.locator(`[data-msg="card-${i}"] .proposal`).innerText();
      assert.ok(body.includes(proposals[i].new_statement));
    }

    await cards[0].click();
    await page.waitForFunction(() => document.querySelector('[data-msg="card-0"] button').disabled);
    // Simulate a redundant handler invocation while the original request is pending.
    await cards[0].evaluate((button) => { void button.onclick(); });
    releaseCommit();
    await page.getByText("Fixture: stale correction", { exact: true }).waitFor();
    assert.deepEqual(requests, [{ proposal: proposals[0], conversation_id: conversation.id }]);
    assert.equal(await cards[0].isEnabled(), true);

    rejectCommit = false;
    await cards[1].click();
    await page.locator("#consolidate-view").waitFor({ state: "visible" });
    assert.deepEqual(requests, proposals.map((proposal) => ({ proposal, conversation_id: conversation.id })));
    console.log("PACKAGED_CORRECTION_CARDS_OK: exact proposals and sources, stale error, duplicate suppression");
  } finally {
    if (app) await app.close();
    fs.rmSync(home, { recursive: true, force: true });
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });

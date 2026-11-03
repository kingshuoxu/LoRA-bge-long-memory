/**
 * 用真实 Electron 窗口走一遍中文界面。
 * 训练在 LORA_MEMORY_E2E_FAST=1 时只跑一轮，事实仍写入记忆。
 */
const fs = require("fs");
const os = require("os");
const path = require("path");
const { _electron: electron } = require("playwright");

const root = path.resolve(__dirname, "..", "..");
const shotDir = path.join(root, "desktop", "e2e-shots", "0.2.9");
const pdf = path.join(root, "tests", "fixtures", "wugang", "wugang_chrome.pdf");
const report = [];

function note(line) {
  report.push(line);
  console.log(line);
}

async function shot(page, name) {
  fs.mkdirSync(shotDir, { recursive: true });
  const file = path.join(shotDir, name);
  await page.screenshot({ path: file, fullPage: false });
  note(`截图 ${path.relative(root, file)}`);
}

async function waitText(page, text, timeout = 120000) {
  await page.getByText(text, { exact: false }).first().waitFor({ timeout });
}

async function assertAnswer(page, text) {
  const body = page.locator("#messages .bubble.assistant .body").last();
  await body.waitFor({ timeout: 120000 });
  await page.waitForFunction((needle) => {
    const nodes = [...document.querySelectorAll("#messages .bubble.assistant .body")];
    const last = nodes[nodes.length - 1];
    return last && last.textContent.includes(needle);
  }, text);
  const content = (await body.innerText()).trim();
  if (!content) throw new Error(`回答是空的，期望包含「${text}」`);
  if (!content.includes(text)) throw new Error(`回答没有「${text}」：${content}`);
  const box = await body.boundingBox();
  if (!box || box.height < 8 || box.width < 8) throw new Error(`回答没有画出来：${content}`);
  await page.locator("#typing").waitFor({ state: "hidden", timeout: 20000 });
}

async function send(page, text) {
  const input = page.locator("#input");
  await input.fill(text);
  await page.locator("#send").click();
  await page.locator(".bubble.user", { hasText: text }).first().waitFor({ timeout: 20000 });
}

async function main() {
  if (!fs.existsSync(pdf)) throw new Error(`缺少 ${pdf}`);
  const home = fs.mkdtempSync(path.join(os.tmpdir(), "yingyu-e2e-"));
  const modelSrc = process.env.LORA_MEMORY_MODELS;
  if (modelSrc && fs.existsSync(modelSrc)) {
    fs.mkdirSync(path.join(home, "models"), { recursive: true });
    for (const name of fs.readdirSync(modelSrc)) {
      const from = path.join(modelSrc, name);
      const to = path.join(home, "models", name);
      try { fs.symlinkSync(from, to); } catch (err) { fs.cpSync(from, to, { recursive: true }); }
    }
  }
  const env = {
    ...process.env,
    LORA_MEMORY_HOME: home,
    LORA_MEMORY_MODELS: path.join(home, "models"),
    LORA_MEMORY_E2E_FAST: "1",
    LORA_MEMORY_E2E_FILES: [pdf, path.join(root, "tests/fixtures/wugang/wugang.docx"), path.join(root, "tests/fixtures/wugang/wugang.epub")].join("\n"),
    LORA_MEMORY_REPO_EXPERTS: "/tmp/yingyu-no-repo-experts",
  };
  const unpackedDir = path.join(root, "desktop", "dist", "linux-unpacked");
  const executablePath = ["lora-bge-memory", "yingyu", "Yingyu"]
    .map((name) => path.join(unpackedDir, name))
    .find((file) => fs.existsSync(file)) || "";
  const app = await electron.launch({
    executablePath: executablePath || undefined,
    args: executablePath
      ? ["--no-sandbox", "--disable-gpu", `--user-data-dir=${home}`]
      : [path.join(root, "desktop"), "--no-sandbox", "--disable-gpu"],
    cwd: path.join(root, "desktop"),
    env,
    timeout: 120000,
  });
  const page = await app.firstWindow();
  page.setDefaultTimeout(180000);
  page.on("dialog", (dialog) => dialog.accept());
  try {
    const boot = page.locator("#boot");
    if (await boot.isVisible().catch(() => false)) {
      await shot(page, "00-boot.png");
    }
    await page.locator("#app").waitFor({ state: "visible", timeout: 600000 });
    await shot(page, "01-ready.png");

    await send(page, "我叫徐金朔");
    await waitText(page, "你是徐金朔");
    await shot(page, "02-taught-name.png");
    note("Q: 我叫徐金朔 → 记成使用者的名字");

    await page.locator("#nav-consolidate").click();
    await waitText(page, "我叫徐金朔");
    await waitText(page, "全部训练");
    await shot(page, "03-pending-name.png");
    const train = page.locator(".train-all").first();
    const toast = page.locator("#toast");
    if (await toast.isVisible().catch(() => false)) {
      const a = await toast.boundingBox();
      const b = await train.boundingBox();
      if (a && b && a.y + a.height > b.y && a.y < b.y + b.height && a.x < b.x + b.width && a.x + a.width > b.x) {
        throw new Error("提示盖住了全部训练");
      }
    }
    await train.click();
    await page.locator("#jobbar").waitFor({ state: "visible", timeout: 60000 }).catch(() => {});
    await shot(page, "04-training-name.png");
    await page.waitForFunction(() => {
      const bar = document.getElementById("jobbar");
      const pending = document.getElementById("pending-box");
      const running = bar && !bar.hidden;
      const still = pending && pending.textContent.includes("徐金朔");
      return !running && !still;
    }, null, { timeout: 180000 });
    await shot(page, "05-name-trained.png");

    await page.locator("#new-chat").click();
    await send(page, "我是谁？");
    await assertAnswer(page, "你是徐金朔");
    await page.locator("#messages .recall-chip").getByText("关于你").waitFor();
    const who = await page.locator("#messages .bubble.assistant").last().innerText();
    if (who.includes("通义") || who.includes("李华")) throw new Error(`基座编造了身份：${who}`);
    await shot(page, "06-who-am-i.png");
    note("Q: 我是谁？");
    note(`screen: ${who.replace(/\s+/g, " ").slice(0, 180)}`);

    await send(page, "我叫什么名字？");
    await assertAnswer(page, "徐金朔");
    await shot(page, "06b-my-name.png");
    await send(page, "我的名字是什么？");
    await assertAnswer(page, "徐金朔");
    await shot(page, "06c-name-what.png");
    await send(page, "你是谁？");
    await assertAnswer(page, "萤语");
    const assistant = await page.locator("#messages .bubble.assistant .body").last().innerText();
    if (assistant.includes("我是徐金朔") || assistant.includes("徐金朔")) {
      throw new Error(`「你是谁」不该用用户的名字：${assistant}`);
    }
    await shot(page, "06d-who-are-you.png");
    note("Q: 你是谁？ 没有把用户的名字当成助手");

    await page.locator("#nav-nebula").click();
    await page.waitForFunction(() => {
      return [...document.querySelectorAll(".nebula-label")].some((node) => {
        const text = node.textContent || "";
        return text.includes("徐金朔") && !text.includes("我叫");
      });
    }, null, { timeout: 20000 });
    const nebulaText = await page.locator("#nebula-view").innerText();
    if (nebulaText.includes("未调用记忆")) throw new Error("星云页不该出现「未调用记忆」");
    await shot(page, "06e-nebula-value.png");
    note("星云节点显示徐金朔，不是整句");

    await page.locator("#nav-chat").click();
    await page.locator("#open-settings").click();
    await page.locator("#settings .sheet").waitFor({ state: "visible" });
    const sheetColor = await page.locator("#settings .sheet").evaluate((el) => getComputedStyle(el).backgroundColor);
    const parts = (sheetColor.match(/rgba?\(([^)]+)\)/) || ["", ""])[1].split(",").map((item) => item.trim());
    const alpha = parts.length >= 4 ? Number(parts[3]) : 1;
    if (!sheetColor || !(alpha >= 0.95)) throw new Error(`设置面板不够实：${sheetColor}`);
    const hint = await page.locator("#settings").innerText();
    if (/latest-|blockmap/i.test(hint)) throw new Error("设置里不该出现安装包的技术文件名");
    await shot(page, "06f-settings.png");
    await page.locator("#settings-close").click();

    await page.locator("#import-doc").click();
    await page.locator("#doc-review").waitFor({ state: "visible", timeout: 180000 });
    await waitText(page, "1873");
    await waitText(page, "四十二米");
    const review = await page.locator("#doc-review").innerText();
    if (review.includes("1873") && review.includes("塔高") && !review.includes("1873年，塔高\n") ) {
      note("重点保持整句");
    }
    await shot(page, "07-review.png");
    await page.locator("#doc-review-skip").click();

    await page.locator("#nav-chat").click();
    await send(page, "白鹭塔建于哪一年？");
    await page.waitForFunction(() => {
      const bodies = [...document.querySelectorAll("#messages .bubble.assistant .body")];
      const last = bodies[bodies.length - 1];
      return last && last.textContent.includes("1873") && last.textContent.includes("四十二米");
    });
    await waitText(page, "第3页");
    await shot(page, "08-year-page.png");
    note("Q: 白鹭塔建于哪一年？ expect 1873 / 第3页");

    await send(page, "星砂盐什么时候晾晒？");
    await page.waitForFunction(() => {
      const bodies = [...document.querySelectorAll("#messages .bubble.assistant .body")];
      const last = bodies[bodies.length - 1];
      return last && last.textContent.includes("霜降");
    });
    await waitText(page, "第6页");
    await shot(page, "09-salt.png");

    await send(page, "柯小满的海鸥叫什么？");
    await assertAnswer(page, "阿哨");
    await waitText(page, "第9页");
    await shot(page, "10-gull.png");

    await send(page, "雾港的市长是谁？");
    await assertAnswer(page, "没有找到相关内容");
    await waitText(page, "雾港灯塔志");
    await shot(page, "11-mayor.png");
    note("Q: 雾港的市长是谁？ → 《雾港灯塔志》里没有找到相关内容。");

    await page.locator("#memory-tab").click();
    await page.locator("#memory-view").getByText("雾港灯塔志").waitFor();
    await page.locator("#memory-view").getByText("选择要巩固的重点").click();
    await page.locator("#doc-review-add").click();
    await page.locator("#toast").getByText("已放入待巩固").waitFor();
    await page.locator("#nav-consolidate").click();
    await page.locator("#pending-box").getByText("1873").waitFor();
    await page.locator("#pending-box").getByText("四十二米").waitFor();
    await shot(page, "12-doc-pending.png");

    await page.locator("#memory-tab").click();
    await page.locator("#memory-view").getByText("雾港灯塔志").waitFor();
    await page.locator("#memory-view").getByText("1873").waitFor();
    await shot(page, "13-library.png");

    await page.locator("#nav-consolidate").click();
    await page.locator("#consolidate-view .train-all").click();
    await page.waitForFunction(() => {
      const box = document.getElementById("pending-box");
      const bar = document.getElementById("jobbar");
      const running = bar && !bar.hidden;
      const text = box ? box.textContent : "";
      return !running && !text.includes("1873") && !text.includes("全部训练");
    }, null, { timeout: 180000 });
    await shot(page, "14-pending-cleared.png");

    await page.locator("#memory-tab").click();
    await page.locator("#memory-view [data-del-doc]").click();
    await page.waitForFunction(() => !document.querySelector("#memory-view [data-del-doc]"), null, { timeout: 20000 });
    await page.locator("#memory-view").getByText("还没有导入的文档").waitFor();
    await shot(page, "15-doc-deleted.png");

    await page.locator("#new-chat").click();
    await send(page, "白鹭塔建于哪一年？");
    await assertAnswer(page, "1873");
    const memory = await page.locator("#messages .bubble.assistant .body").last().innerText();
    if (memory.includes("没有找到")) throw new Error("删书之后年份不该说找不到");
    if (!memory.includes("四十二米")) throw new Error(`年份答句不完整：${memory}`);
    await shot(page, "16-year-from-memory.png");
    note("删书之后仍从记忆答出 1873");
    note(`screen: ${memory.replace(/\s+/g, " ").slice(0, 180)}`);

    await page.locator("#import-doc").click();
    await page.locator("#doc-review-source").getByText("DOCX").waitFor({ timeout: 120000 });
    await shot(page, "17-docx.png");
    await page.locator("#doc-review-skip").click();
    await page.locator("#import-doc").click();
    await page.locator("#doc-review-source").getByText("EPUB").waitFor({ timeout: 120000 });
    await shot(page, "18-epub.png");
    const docxShot = fs.readFileSync(path.join(shotDir, "17-docx.png"));
    const epubShot = fs.readFileSync(path.join(shotDir, "18-epub.png"));
    if (docxShot.equals(epubShot)) throw new Error("DOCX 和 EPUB 的复核截图不能是同一张");
    await page.locator("#doc-review-skip").click();
    note("DOCX 和 EPUB 都能打开重点复核");

    fs.writeFileSync(path.join(shotDir, "e2e-report.md"), `${report.join("\n")}\n`, "utf8");
    note("E2E_OK");
  } finally {
    await app.close().catch(() => {});
  }
}

main().catch((err) => {
  console.error(err);
  try {
    fs.mkdirSync(shotDir, { recursive: true });
    fs.writeFileSync(path.join(shotDir, "e2e-report.md"), `${report.join("\n")}\n\n失败：${err.stack || err}\n`, "utf8");
  } catch (writeErr) {
    console.error(writeErr);
  }
  process.exit(1);
});

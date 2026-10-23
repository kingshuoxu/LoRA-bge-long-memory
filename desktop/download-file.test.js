"use strict";

const assert = require("assert");
const crypto = require("crypto");
const fs = require("fs");
const http = require("http");
const os = require("os");
const path = require("path");
const { downloadVerified } = require("./download-file");

const body = Buffer.from("hello-update-payload-0123456789");
const digest = crypto.createHash("sha256").update(body).digest("hex");

function startServer() {
  const ranges = [];
  const server = http.createServer((req, res) => {
    const header = req.headers.range || "";
    if (header.startsWith("bytes=")) {
      const start = Number(header.slice(6).split("-")[0]);
      ranges.push(start);
      const slice = body.subarray(start);
      res.writeHead(206, {
        "Content-Length": slice.length,
        "Content-Range": `bytes ${start}-${body.length - 1}/${body.length}`,
      });
      res.end(slice);
      return;
    }
    ranges.push(0);
    res.writeHead(200, { "Content-Length": body.length });
    res.end(body);
  });
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      resolve({ server, ranges, url: `http://127.0.0.1:${port}/pkg.dmg` });
    });
  });
}

async function main() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "lora-dl-"));
  const dest = path.join(dir, "pkg.dmg");
  const { server, ranges, url } = await startServer();
  try {
    fs.writeFileSync(`${dest}.partial`, body.subarray(0, 6));
    await downloadVerified(url, dest, digest, null, 5000);
    assert.deepEqual(ranges, [6]);
    assert.equal(fs.readFileSync(dest).equals(body), true);
    assert.equal(fs.existsSync(`${dest}.partial`), false);

    ranges.length = 0;
    await downloadVerified(url, dest, digest, null, 5000);
    assert.deepEqual(ranges, []);

    fs.rmSync(dest);
    await assert.rejects(() => downloadVerified(url, dest, "0".repeat(64), null, 5000), /SHA256/);
    assert.equal(fs.existsSync(dest), false);
    assert.equal(fs.existsSync(`${dest}.partial`), false);
    await assert.rejects(() => downloadVerified(url, dest, "abc", null, 5000), /SHA256/);
  } finally {
    server.close();
    fs.rmSync(dir, { recursive: true, force: true });
  }
  console.log("DOWNLOAD_FILE_OK");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
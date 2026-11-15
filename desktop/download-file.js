"use strict";

const crypto = require("crypto");
const fs = require("fs");
const http = require("http");
const https = require("https");
const path = require("path");

function sha256File(file) {
  return new Promise((resolve, reject) => {
    const hash = crypto.createHash("sha256");
    const input = fs.createReadStream(file);
    input.on("error", reject);
    input.on("data", (chunk) => hash.update(chunk));
    input.on("end", () => resolve(hash.digest("hex")));
  });
}

function downloadToPartial(url, partial, onProgress, stallMs, redirects) {
  if (redirects > 5) return Promise.reject(new Error("重定向过多"));
  return new Promise((resolve, reject) => {
    let settled = false;
    let timer = null;
    const finish = (err, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (err) reject(err);
      else resolve(value);
    };
    const bump = () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        req.destroy(new Error("下载没有进展"));
      }, stallMs);
    };
    let start = 0;
    if (fs.existsSync(partial)) start = fs.statSync(partial).size;
    const headers = { "User-Agent": "lora-bge-memory" };
    if (start > 0) headers.Range = `bytes=${start}-`;
    const lib = url.startsWith("http:") ? http : https;
    const req = lib.get(url, { headers }, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        res.resume();
        clearTimeout(timer);
        downloadToPartial(new URL(res.headers.location, url).href, partial, onProgress, stallMs, redirects + 1).then(
          (value) => finish(null, value),
          (err) => finish(err)
        );
        return;
      }
      if (res.statusCode === 416) {
        res.resume();
        clearTimeout(timer);
        if (start === 0) {
          finish(new Error("HTTP 416"));
          return;
        }
        fs.rmSync(partial, { force: true });
        downloadToPartial(url, partial, onProgress, stallMs, redirects).then(
          (value) => finish(null, value),
          (err) => finish(err)
        );
        return;
      }
      let offset = start;
      const append = res.statusCode === 206 && start > 0;
      if (!append && res.statusCode === 200) offset = 0;
      else if (res.statusCode !== 206) {
        res.resume();
        finish(new Error(`HTTP ${res.statusCode}`));
        return;
      }
      const length = Number(res.headers["content-length"] || 0);
      const total = length ? offset + length : 0;
      let got = offset;
      fs.mkdirSync(path.dirname(partial), { recursive: true });
      const file = fs.createWriteStream(partial, { flags: append ? "a" : "w" });
      res.on("data", (chunk) => {
        bump();
        got += chunk.length;
        if (onProgress) onProgress(got, total);
      });
      res.on("error", (err) => finish(err));
      res.pipe(file);
      file.on("finish", () => file.close(() => finish(null, partial)));
      file.on("error", (err) => finish(err));
    });
    bump();
    req.on("error", (err) => finish(err));
  });
}

async function downloadVerified(url, dest, expectedSha256, onProgress, stallMs) {
  const want = String(expectedSha256 || "").trim().toLowerCase();
  if (!/^[a-f0-9]{64}$/.test(want)) throw new Error("更新包没有 SHA256");
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  if (fs.existsSync(dest) && await sha256File(dest) === want) {
    if (onProgress) onProgress(fs.statSync(dest).size, fs.statSync(dest).size);
    return dest;
  }
  if (fs.existsSync(dest)) fs.rmSync(dest);
  const partial = `${dest}.partial`;
  if (fs.existsSync(partial) && await sha256File(partial) === want) {
    fs.renameSync(partial, dest);
    return dest;
  }
  await downloadToPartial(url, partial, onProgress, stallMs || 30000, 0);
  const got = await sha256File(partial);
  if (got !== want) {
    fs.rmSync(partial, { force: true });
    throw new Error("SHA256 不一致");
  }
  fs.renameSync(partial, dest);
  return dest;
}

module.exports = {
  sha256File,
  downloadVerified,
};

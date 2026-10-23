"use strict";

const assert = require("assert");
const plan = require("./update-plan");

assert.equal(plan.desktopTagVersion("desktop-v0.2.0"), "0.2.0");
assert.equal(plan.desktopTagVersion("v0.2.0"), "");
assert.equal(plan.compareVersions("0.1.9", "0.2.0") < 0, true);
assert.equal(plan.compareVersions("0.2.0", "0.2.0"), 0);

const newest = plan.newestDesktopRelease([
  { tag_name: "desktop-v0.1.0", prerelease: true, body: "old" },
  { tag_name: "v1.0.0", prerelease: true, body: "not desktop" },
  { tag_name: "desktop-v0.2.0", prerelease: true, draft: true, body: "draft" },
  { tag_name: "desktop-v0.2.0", prerelease: false, body: "stable flag" },
  { tag_name: "desktop-v0.1.9", prerelease: true, body: "notes" },
]);
assert.equal(newest.version, "0.1.9");
assert.equal(newest.notes, "notes");

assert.deepEqual(plan.feedUrls("https://mirror.example/lora", newest), [
  "https://github.com/kingshuoxu/LoRA-bge-long-memory/releases/download/desktop-v0.1.9/",
  "https://mirror.example/lora/",
]);
assert.deepEqual(plan.feedUrls("", null), []);

assert.equal(plan.installMode({ packaged: false, platform: "linux", appImage: true }), "dev");
assert.equal(plan.installMode({ packaged: true, platform: "linux", appImage: true }), "appimage");
assert.equal(plan.installMode({ packaged: true, platform: "linux", appImage: false }), "deb");
assert.equal(plan.installMode({ packaged: true, platform: "win32" }), "nsis");
assert.equal(plan.installMode({ packaged: true, platform: "darwin", macSigned: false }), "mac-manual");
assert.equal(plan.installMode({ packaged: true, platform: "darwin", macSigned: true }), "mac-auto");

const assets = [
  { name: "LoRA-bge-memory-0.2.0-linux-amd64.deb" },
  { name: "LoRA-bge-memory-0.2.0-linux-x86_64.AppImage" },
  { name: "LoRA-bge-memory-0.2.0-mac-arm64.dmg" },
  { name: "LoRA-bge-memory-0.2.0-mac-x64.dmg" },
  { name: "LoRA-bge-memory-0.2.0-mac-arm64.zip" },
];
assert.equal(plan.pickAsset(assets, "deb", "x64").name.endsWith(".deb"), true);
assert.equal(plan.pickAsset(assets, "mac-manual", "arm64").name.includes("arm64"), true);
assert.equal(plan.pickAsset(assets, "mac-manual", "x64").name.includes("x64"), true);
assert.equal(plan.pickAsset(assets, "mac-auto", "arm64").name.endsWith(".zip"), true);
assert.equal(plan.notesText([{ version: "0.2.0", note: "修复" }, "第二段"]), "修复\n\n第二段");

console.log("UPDATE_PLAN_OK");

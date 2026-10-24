"use strict";

const GITHUB_OWNER = "kingshuoxu";
const GITHUB_REPO = "LoRA-bge-long-memory";
const TAG_PREFIX = "desktop-v";

function desktopTagVersion(tag) {
  const matched = new RegExp("^" + TAG_PREFIX + "(\\d+\\.\\d+\\.\\d+(?:[-+][0-9A-Za-z.-]+)?)$").exec(String(tag || ""));
  return matched ? matched[1] : "";
}

function compareVersions(left, right) {
  const split = (value) => String(value || "0").split(/[.+-]/).map((part) => (/^\d+$/.test(part) ? Number(part) : part));
  const a = split(left);
  const b = split(right);
  const length = Math.max(a.length, b.length);
  for (let index = 0; index < length; index += 1) {
    const av = a[index] === undefined ? 0 : a[index];
    const bv = b[index] === undefined ? 0 : b[index];
    if (av === bv) continue;
    if (typeof av === "number" && typeof bv === "number") return av < bv ? -1 : 1;
    return String(av) < String(bv) ? -1 : 1;
  }
  return 0;
}

function newestDesktopRelease(releases) {
  let best = null;
  for (const release of releases || []) {
    if (!release || release.draft) continue;
    if (release.prerelease === false) continue;
    const version = desktopTagVersion(release.tag_name);
    if (!version) continue;
    if (!best || compareVersions(version, best.version) > 0) {
      best = {
        tag: release.tag_name,
        version,
        notes: String(release.body || "").trim(),
        assets: Array.isArray(release.assets) ? release.assets : [],
      };
    }
  }
  return best;
}

function githubDownloadBase(tag) {
  return `https://github.com/${GITHUB_OWNER}/${GITHUB_REPO}/releases/download/${tag}/`;
}

function normalizeMirror(url) {
  const text = String(url || "").trim();
  if (!text) return "";
  return text.endsWith("/") ? text : `${text}/`;
}

function feedUrls(mirror, release) {
  const urls = [];
  if (release && release.tag) urls.push(githubDownloadBase(release.tag));
  const mirrorUrl = normalizeMirror(mirror);
  if (mirrorUrl) urls.push(mirrorUrl);
  return urls;
}

function installMode(info) {
  if (!info || !info.packaged) return "dev";
  if (info.platform === "win32") return "nsis";
  if (info.platform === "linux") return info.appImage ? "appimage" : "deb";
  if (info.platform === "darwin") return "mac-manual";
  return "manual";
}

function assetNameRank(name, mode, arch) {
  const lower = String(name || "").toLowerCase();
  if (mode === "deb") return lower.endsWith(".deb") ? 2 : 0;
  if (mode === "nsis") return lower.endsWith(".exe") ? 2 : 0;
  if (mode === "appimage") return lower.endsWith(".appimage") ? 2 : 0;
  if (mode === "mac-manual") {
    const dmg = lower.endsWith(".dmg");
    const zip = lower.endsWith(".zip");
    if (!dmg && !zip) return 0;
    let rank = dmg ? 2 : 1;
    if (arch === "arm64" && lower.includes("arm64")) rank += 2;
    if (arch !== "arm64" && (lower.includes("x64") || lower.includes("x86_64"))) rank += 2;
    return rank;
  }
  return 0;
}

function pickAsset(assets, mode, arch) {
  let best = null;
  let bestRank = 0;
  for (const asset of assets || []) {
    const name = asset.name || asset.url || "";
    const rank = assetNameRank(name, mode, arch);
    if (rank > bestRank) {
      best = asset;
      bestRank = rank;
    }
  }
  return best;
}

function notesText(notes) {
  if (notes == null) return "";
  if (typeof notes === "string") return notes.trim();
  if (Array.isArray(notes)) {
    return notes.map((item) => {
      if (typeof item === "string") return item;
      if (item && item.note) return String(item.note);
      return "";
    }).filter(Boolean).join("\n\n").trim();
  }
  return "";
}

module.exports = {
  GITHUB_OWNER,
  GITHUB_REPO,
  TAG_PREFIX,
  desktopTagVersion,
  compareVersions,
  newestDesktopRelease,
  githubDownloadBase,
  normalizeMirror,
  feedUrls,
  installMode,
  pickAsset,
  notesText,
};

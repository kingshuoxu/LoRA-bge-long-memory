#!/usr/bin/env python3
"""Walk the same mirror list as AppUpdate.kt over the real network.

Direct GitHub is recorded, then skipped. A later mirror must return a real
release list and update.json with versionCode > 1004, plus an APK that starts
with the zip magic. HTML landing pages do not count.
"""

import json
import pathlib
import re
import ssl
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
SOURCE = ROOT / "android/apk/app/src/main/java/com/lorabge/memory/AppUpdate.kt"
REPO = "kingshuoxu/LoRA-bge-long-memory"
CURRENT = 1004
API = f"https://api.github.com/repos/{REPO}/releases?per_page=30"
CTX = ssl.create_default_context()


def prefixes():
    text = SOURCE.read_text(encoding="utf-8")
    block = re.search(r"val UPDATE_MIRROR_PREFIXES: List<String> = listOf\((.*?)\)", text, re.S)
    if not block:
        raise SystemExit("AppUpdate.kt 里没有 UPDATE_MIRROR_PREFIXES")
    found = re.findall(r'"(https://[^"]+)"', block.group(1))
    if len(found) < 2:
        raise SystemExit(f"镜像太少: {found}")
    if any("ghproxy.net" in item or "mirror.ghproxy.com" in item or "releases/latest" in item for item in found):
        raise SystemExit(f"失效镜像还在列表里: {found}")
    return found


def fetch(url, kind):
    req = urllib.request.Request(url, headers={"User-Agent": "lorabge-memory/0.1"})
    if kind == "apk":
        req.add_header("Range", "bytes=0-15")
    try:
        with urllib.request.urlopen(req, timeout=25, context=CTX) as resp:
            body = resp.read(64 if kind == "apk" else 2_000_000)
            code = resp.status
    except urllib.error.HTTPError as err:
        return {"url": url, "kind": kind, "ok": False, "detail": f"HTTP {err.code}"}
    except Exception as err:
        return {"url": url, "kind": kind, "ok": False, "detail": f"{type(err).__name__}: {err}"[:180]}
    head = body[:200].lstrip().lower()
    if head.startswith(b"<") or b"<html" in head or b"<!doctype" in head:
        return {"url": url, "kind": kind, "ok": False, "detail": f"HTTP {code} HTML"}
    if kind == "apk":
        if body.startswith(b"PK"):
            return {"url": url, "kind": kind, "ok": True, "detail": f"HTTP {code} APK"}
        return {"url": url, "kind": kind, "ok": False, "detail": f"HTTP {code} not-apk {body[:12]!r}"}
    try:
        data = json.loads(body.decode("utf-8"))
    except Exception as err:
        return {"url": url, "kind": kind, "ok": False, "detail": f"HTTP {code} not-json {err}"[:180]}
    if kind == "api":
        if not isinstance(data, list):
            return {"url": url, "kind": kind, "ok": False, "detail": "JSON 不是发布列表"}
        tags = [row.get("tag_name") for row in data if str(row.get("tag_name", "")).startswith("android-v")]
        codes = []
        for tag in tags:
            match = re.match(r"android-v(\d+)\.(\d+)\.(\d+)$", str(tag))
            if match:
                major, minor, patch = (int(part) for part in match.groups())
                codes.append(major * 1_000_000 + minor * 1_000 + patch)
        newer = [code for code in codes if code > CURRENT]
        if not newer:
            return {"url": url, "kind": kind, "ok": False, "detail": f"JSON 没有高于 {CURRENT} 的 android-v {tags}"}
        return {"url": url, "kind": kind, "ok": True, "detail": f"HTTP {code} JSON {tags}", "versionCode": max(newer)}
    if not isinstance(data, dict):
        return {"url": url, "kind": kind, "ok": False, "detail": "JSON 不是 update.json"}
    code_value = data.get("versionCode")
    name = data.get("versionName")
    if code_value == 1005 and name == "0.1.5" and re.fullmatch(r"[0-9a-fA-F]{64}", str(data.get("sha256", ""))):
        return {"url": url, "kind": kind, "ok": True, "detail": "HTTP %s JSON versionCode 1005" % code, "versionCode": 1005}
    return {"url": url, "kind": kind, "ok": False, "detail": f"JSON versionCode={code_value} versionName={name}"}


def first_ok(rows):
    for row in rows:
        if row["ok"]:
            return row
    return None


def main():
    mirror_prefixes = prefixes()
    direct = {
        "api": API,
        "json": f"https://github.com/{REPO}/releases/download/android-v0.1.5/update.json",
        "apk": f"https://github.com/{REPO}/releases/download/android-v0.1.5/app-debug.apk",
    }
    print("prefixes", " ".join(mirror_prefixes))
    direct_rows = []
    mirror_rows = {kind: [] for kind in direct}
    for kind, url in direct.items():
        row = fetch(url, kind)
        direct_rows.append(row)
        print(f"DIRECT {kind} {row['detail']} {url}")
        for prefix in mirror_prefixes:
            mirrored = fetch(prefix + url, kind)
            mirror_rows[kind].append(mirrored)
            print(f"MIRROR {kind} {mirrored['detail']} {prefix + url}")
    api_hit = first_ok(mirror_rows["api"])
    json_hit = first_ok(mirror_rows["json"])
    apk_hit = first_ok(mirror_rows["apk"])
    print("--- skipped direct ---")
    if api_hit:
        print(f"release list {api_hit['versionCode']} via {api_hit['url']}")
    if json_hit:
        print(f"update.json {json_hit['versionCode']} via {json_hit['url']}")
    if apk_hit:
        print(f"apk via {apk_hit['url']}")
    ok = (
        api_hit is not None
        and api_hit["versionCode"] >= 1005
        and json_hit is not None
        and json_hit["versionCode"] == 1005
        and apk_hit is not None
    )
    print("PASS" if ok else "FAIL")
    print("from", CURRENT, "to", json_hit["versionCode"] if json_hit else "none")
    if not ok:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

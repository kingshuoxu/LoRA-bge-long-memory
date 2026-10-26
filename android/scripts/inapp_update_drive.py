#!/usr/bin/env python3
"""Tap 检查更新 on the already-installed published 0.1.4 and wait for 0.1.5."""

import os
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ADB_BIN = os.environ.get("ADB", "adb")
SERIAL = os.environ["ANDROID_SERIAL"]
STAGE = Path(os.environ["INAPP_STAGE"])
SHOTS = STAGE / "shots"
SHOTS.mkdir(parents=True, exist_ok=True)
EXPECTED_NEW_SHA = "7efa7e71366df3a03b6dc3272f3f6feea94044b148011436ac5c865c2070a861"
EXPECTED_NEW_SIZE = 51542731
INSTALL_LABELS = {"Install", "Update", "安装", "更新", "Install anyway", "More details", "Update anyway"}


def adb(*args, timeout=90, check=True):
    proc = subprocess.run(
        [ADB_BIN, "-s", SERIAL, *args],
        capture_output=True,
        timeout=timeout,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"adb {' '.join(args)} -> {proc.returncode} {proc.stderr.decode('utf-8', 'replace')[:400]}")
    return proc


def version_info():
    text = adb("shell", "dumpsys", "package", "com.lorabge.memory", timeout=40).stdout.decode("utf-8", "replace")
    code = ""
    name = ""
    for line in text.splitlines():
        if "versionCode=" in line and not code:
            match = re.search(r"versionCode=(\d+)", line)
            if match:
                code = match.group(1)
        if "versionName=" in line and not name:
            match = re.search(r"versionName=([0-9.]+)", line)
            if match:
                name = match.group(1)
        if code and name:
            break
    return code, name


def shot(name):
    raw = subprocess.run(
        [ADB_BIN, "-s", SERIAL, "exec-out", "screencap", "-p"],
        capture_output=True,
        timeout=40,
    ).stdout
    path = SHOTS / f"{name}.png"
    if raw.startswith(b"\x89PNG"):
        path.write_bytes(raw)
        return
    remote = f"/data/local/tmp/{name}.png"
    adb("shell", "screencap", "-p", remote, check=False)
    adb("pull", remote, str(path), check=False)


def dump_root():
    remote = "/data/local/tmp/uidump.xml"
    local = STAGE / "uidump.xml"
    adb("shell", "uiautomator", "dump", remote, check=False, timeout=40)
    adb("pull", remote, str(local), check=False)
    if not local.exists() or local.stat().st_size < 50:
        return None
    try:
        return ET.parse(local).getroot()
    except ET.ParseError:
        return None


def node_blob(node):
    return (node.attrib.get("text", "") + "\n" + node.attrib.get("content-desc", "")).strip()


def center(node):
    match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.attrib.get("bounds", ""))
    if not match:
        return None
    x1, y1, x2, y2 = (int(part) for part in match.groups())
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1 + x2) // 2, (y1 + y2) // 2


def find_exact(root, needle):
    if root is None:
        return None
    for node in root.iter("node"):
        text = node.attrib.get("text", "")
        desc = node.attrib.get("content-desc", "")
        if text == needle or desc == needle:
            point = center(node)
            if point:
                return point
    return None


def find_contains(root, needle):
    if root is None:
        return None
    for node in root.iter("node"):
        if needle in node_blob(node):
            point = center(node)
            if point:
                return point
    return None


def visible_text(root):
    if root is None:
        return ""
    parts = []
    for node in root.iter("node"):
        blob = node_blob(node)
        if blob:
            parts.append(blob.replace("\n", " "))
    return " | ".join(parts)


def tap(point):
    adb("shell", "input", "tap", str(point[0]), str(point[1]))


def swipe_up():
    adb("shell", "input", "swipe", "540", "1800", "540", "700", "350")


def wait_exact(needle, seconds, shot_name):
    deadline = time.time() + seconds
    last = ""
    while time.time() < deadline:
        root = dump_root()
        last = visible_text(root)
        point = find_exact(root, needle)
        if point:
            shot(shot_name)
            return point, last
        time.sleep(2)
    shot(shot_name + "-missing")
    raise RuntimeError(f"没找到 {needle}. 界面: {last[:800]}")


def main():
    before_code, before_name = version_info()
    (STAGE / "version-before.txt").write_text(f"{before_code} {before_name}\n", encoding="utf-8")
    if before_code != "1004" or before_name != "0.1.4":
        raise SystemExit(f"安装后不是 0.1.4/1004，而是 {before_name}/{before_code}")

    adb("shell", "am", "start", "-n", "com.lorabge.memory/.MainActivity")
    time.sleep(3)
    settings, _ = wait_exact("settings", 40, "01-home")
    tap(settings)
    time.sleep(1)
    check = None
    seen = ""
    for _ in range(6):
        root = dump_root()
        seen = visible_text(root)
        check = find_exact(root, "检查更新")
        if check:
            break
        swipe_up()
        time.sleep(1)
    shot("02-settings")
    if not check:
        raise SystemExit(f"设置里没有「检查更新」。界面: {seen[:800]}")
    if "0.1.4" not in seen and "长期记忆 0.1.4" not in seen:
        (STAGE / "settings-text.txt").write_text(seen, encoding="utf-8")
    tap(check)
    started = time.time()
    offer = None
    offer_text = ""
    deadline = time.time() + 150
    while time.time() < deadline:
        root = dump_root()
        offer_text = visible_text(root)
        if "下载并安装" in offer_text or "可以更新 0.1.5" in offer_text or "版本 0.1.5" in offer_text:
            offer = find_exact(root, "下载并安装")
            break
        if any(bad in offer_text for bad in ("连不上", "connection closed", "connection abort", "Software caused", "检查失败")):
            shot("03-check-failed")
            (STAGE / "offer-text.txt").write_text(offer_text, encoding="utf-8")
            raise SystemExit(f"检查更新失败。界面: {offer_text[:800]}")
        time.sleep(2)
    shot("03-offer")
    (STAGE / "offer-text.txt").write_text(offer_text, encoding="utf-8")
    if offer is None:
        raise SystemExit(f"没有出现 0.1.5 的下载按钮。界面: {offer_text[:800]}")
    found_after = round(time.time() - started, 1)
    tap(offer)

    installer_tapped = False
    updated = False
    end = time.time() + 600
    last = offer_text
    while time.time() < end:
        code, name = version_info()
        if code == "1005" and name == "0.1.5":
            updated = True
            break
        root = dump_root()
        last = visible_text(root)
        for label in INSTALL_LABELS:
            point = find_exact(root, label)
            if point:
                shot("04-installer")
                tap(point)
                installer_tapped = True
                time.sleep(2)
                break
        time.sleep(3)
    shot("04-after-download")
    if not updated:
        (STAGE / "install-text.txt").write_text(last, encoding="utf-8")
        raise SystemExit(f"安装没有完成。最后界面: {last[:800]}")

    adb("shell", "am", "force-stop", "com.lorabge.memory", check=False)
    time.sleep(1)
    adb("shell", "am", "start", "-n", "com.lorabge.memory/.MainActivity")
    time.sleep(3)
    settings, _ = wait_exact("settings", 40, "05-relaunched")
    tap(settings)
    time.sleep(1)
    about = ""
    for _ in range(6):
        root = dump_root()
        about = visible_text(root)
        if "0.1.5" in about:
            break
        swipe_up()
        time.sleep(1)
    shot("05-about")
    (STAGE / "about-text.txt").write_text(about, encoding="utf-8")
    if "0.1.5" not in about:
        raise SystemExit(f"关于页没有 0.1.5。界面: {about[:800]}")

    path_text = adb("shell", "pm", "path", "com.lorabge.memory").stdout.decode("utf-8", "replace")
    apk_path = ""
    for line in path_text.splitlines():
        if line.startswith("package:"):
            apk_path = line.split(":", 1)[1].strip()
            break
    pulled = STAGE / "installed-after.apk"
    sha = ""
    size = 0
    if apk_path:
        adb("pull", apk_path, str(pulled), timeout=180)
        if pulled.exists():
            import hashlib
            data = pulled.read_bytes()
            size = len(data)
            sha = hashlib.sha256(data).hexdigest()
    code, name = version_info()
    report = "\n".join([
        "result=PASS",
        f"before=1004 0.1.4",
        f"after={code} {name}",
        f"offer_seconds={found_after}",
        f"installer_tapped={str(installer_tapped).lower()}",
        f"installed_apk_sha256={sha}",
        f"installed_apk_bytes={size}",
        f"published_0.1.5_sha256={EXPECTED_NEW_SHA}",
        "path=in-app check update, not adb install -r",
    ]) + "\n"
    (STAGE / "result.txt").write_text(report, encoding="utf-8")
    print(report)
    if code != "1005" or name != "0.1.5":
        raise SystemExit("versionCode 没有变成 1005")
    if size == EXPECTED_NEW_SIZE and sha != EXPECTED_NEW_SHA:
        raise SystemExit(f"装上的 APK 大小对上了但 SHA256 不是已发布的 0.1.5: {sha}")


if __name__ == "__main__":
    try:
        main()
    except Exception as err:
        fail = STAGE / "result.txt"
        fail.write_text(f"result=FAIL\n{type(err).__name__}: {err}\n", encoding="utf-8")
        try:
            shot("99-fail")
        except Exception:
            pass
        raise

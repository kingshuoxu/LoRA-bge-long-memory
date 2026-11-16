#!/usr/bin/env python3
"""Host assertions for the candidate PackageInstaller gate (stdlib only)."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

PACKAGE = "com.lorabge.memory"
# Synthetic data, not the user's real profile.
SENTINELS = {
    "files/memory/keep.txt": "keep-memory\n",
    "files/memory/conversations/update-test.json": '{"messages":[{"role":"user","content":"upgrade fixture"}]}\n',
    "files/models/keep.bin": "keep-model\n",
    "shared_prefs/update_test.xml": '<map><string name="keep">yes</string></map>\n',
    "files/setup/e2e": "1\n",
}


def version_code(name):
    if not re.fullmatch(r"\d+\.\d+\.\d+", name):
        raise ValueError("Expected a three-part release version")
    major, minor, patch = map(int, name.split("."))
    if not (0 <= major <= 99 and 0 <= minor <= 999 and 0 <= patch <= 999):
        raise ValueError("Version component out of range")
    return major * 1_000_000 + minor * 1000 + patch


def read_candidate(release):
    meta = json.loads((release / "update.json").read_text())
    blob = (release / "app-debug.apk").read_bytes()
    if meta.get("apk") != "app-debug.apk":
        raise ValueError("Unexpected candidate filename")
    if meta["versionCode"] != version_code(meta["versionName"]) or meta["versionCode"] <= 0:
        raise ValueError("Candidate version does not match manifest")
    validate_installed(meta, meta["versionCode"], meta["versionName"], hashlib.sha256(blob).hexdigest(), len(blob))
    return meta


def baseline_version(meta):
    code = meta["versionCode"] - 1
    return f"{code // 1_000_000}.{code % 1_000_000 // 1000}.{code % 1000}"


def validate_installed(meta, code, name, digest, size):
    # Both size AND digest must match. A missing/wrong size must never bypass SHA.
    if code != meta["versionCode"] or name != meta["versionName"]:
        raise ValueError("Installed version does not match candidate")
    if size <= 0 or size != meta["size"] or digest != meta["sha256"]:
        raise ValueError("Installed bytes do not match candidate")


def adb(*args, check=True, timeout=60):
    return subprocess.run([os.environ.get("ADB", "adb"), "-s", os.environ["ANDROID_SERIAL"], *args],
                          check=check, capture_output=True, timeout=timeout)


def seed(stage):
    for index, (path, value) in enumerate(SENTINELS.items()):
        local = stage / f"seed-{index}"
        local.write_text(value)
        remote = f"/data/local/tmp/update-seed-{index}"
        adb("push", str(local), remote)
        adb("shell", "run-as", PACKAGE, "mkdir", "-p", str(Path(path).parent))
        adb("shell", "run-as", PACKAGE, "cp", remote, path)


def package_version():
    text = adb("shell", "dumpsys", "package", PACKAGE).stdout.decode()
    code = re.search(r"\bversionCode=(\d+)", text)
    name = re.search(r"\bversionName=([^\s]+)", text)
    return (int(code[1]) if code else None, name[1] if name else None)


def confirm_installer(stage):
    # Only click an affirmative button in a system package installer, never in our app.
    adb("shell", "uiautomator", "dump", "/data/local/tmp/update-ui.xml", check=False)
    proc = adb("shell", "cat", "/data/local/tmp/update-ui.xml", check=False)
    (stage / "installer-ui.xml").write_bytes(proc.stdout)
    try:
        root = ET.fromstring(proc.stdout)
    except ET.ParseError:
        return
    for node in root.iter("node"):
        attrs = node.attrib
        if attrs.get("package") not in {"com.google.android.packageinstaller", "com.android.packageinstaller", "com.android.permissioncontroller", "com.google.android.permissioncontroller"}:
            continue
        if attrs.get("text", "").lower() not in {"install", "update", "安装", "更新"} or attrs.get("enabled") != "true":
            continue
        match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", attrs.get("bounds", ""))
        if match:
            x1, y1, x2, y2 = map(int, match.groups())
            adb("shell", "input", "tap", str((x1+x2)//2), str((y1+y2)//2))
            return


def verify(meta, stage):
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        if package_version() == (meta["versionCode"], meta["versionName"]):
            break
        confirm_installer(stage)
        time.sleep(2)
    else:
        raise RuntimeError("Timed out waiting for candidate PackageInstaller update")
    submitted = adb("shell", "run-as", PACKAGE, "cat", "files/update-fixture/submitted").stdout.decode().strip()
    if submitted != meta["sha256"]:
        raise RuntimeError("Production update path did not submit this candidate")
    paths = adb("shell", "pm", "path", PACKAGE).stdout.decode().splitlines()
    if len(paths) != 1 or not paths[0].startswith("package:"):
        raise RuntimeError("Expected one installed base APK")
    installed = paths[0].removeprefix("package:").strip()
    # Avoid adb pull's handling of '=' in /data/app paths.
    adb("shell", "cp", installed, "/data/local/tmp/installed-candidate.apk")
    result = adb("shell", "sha256sum", "/data/local/tmp/installed-candidate.apk").stdout.decode()
    digest = result.split()[0]
    size = int(adb("shell", "stat", "-c", "%s", "/data/local/tmp/installed-candidate.apk").stdout)
    code, name = package_version()
    validate_installed(meta, code, name, digest, size)
    for path, expected in SENTINELS.items():
        actual = adb("exec-out", "run-as", PACKAGE, "cat", path).stdout.decode()
        if actual != expected:
            raise RuntimeError(f"Update did not preserve {path}")
    adb("shell", "am", "force-stop", PACKAGE)
    launch = adb("shell", "am", "start", "-W", "-n", PACKAGE + "/.MainActivity").stdout.decode()
    if "Status: ok" not in launch:
        raise RuntimeError(f"Candidate did not launch: {launch}")
    # am start can report success even if startup immediately crashes or corrupts data.
    time.sleep(5)
    if not adb("shell", "pidof", PACKAGE, check=False).stdout.strip():
        raise RuntimeError("Candidate exited after launch")
    for path, expected in SENTINELS.items():
        actual = adb("exec-out", "run-as", PACKAGE, "cat", path).stdout.decode()
        if actual != expected:
            raise RuntimeError(f"Candidate startup did not preserve {path}")
    report = {"result": "PASS", "versionName": name, "versionCode": code, "sha256": digest,
              "size": size, "preserved": list(SENTINELS),
              "scope": "current-source synthetic baseline; fixture transport; production lookup/download/installer; exact candidate APK"}
    (stage / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


def main():
    action, release = sys.argv[1:3]
    meta = read_candidate(Path(release))
    if action == "prepare":
        print(baseline_version(meta))
        return
    stage = Path(sys.argv[3])
    stage.mkdir(parents=True, exist_ok=True)
    if action == "seed":
        seed(stage)
    elif action == "verify":
        try:
            verify(meta, stage)
        except Exception as err:
            (stage / "result.json").write_text(json.dumps({"result": "FAIL", "error": str(err)}) + "\n")
            raise
    else:
        raise ValueError(action)


if __name__ == "__main__":
    main()

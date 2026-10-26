#!/bin/sh
# 安装已发布的 android-v0.1.4，在模拟器里点「检查更新」，升到已发布的 0.1.5。
# 不用 adb install -r 顶掉。x86_64 要带 ARM 翻译，因为发布包只有 arm64-v8a。
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
SDK=${ANDROID_SDK_ROOT:-${ANDROID_HOME:-/usr/local/lib/android/sdk}}
export ANDROID_SDK_ROOT="$SDK"
export ANDROID_HOME="$SDK"
PORT=${INAPP_PORT:-5584}
AVD=${INAPP_AVD:-lorabge-inapp}
STAGE="$ROOT/android/out/inapp-update"
mkdir -p "$STAGE/shots"
ADB="$SDK/platform-tools/adb"
EMU="$SDK/emulator/emulator"
AAPT=$(find "$SDK/build-tools" -path '*/aapt' | sort | tail -1)
test -x "$ADB"
test -x "$EMU"
test -n "$AAPT"
if [ ! -d "$SDK/system-images/android-35/google_apis/x86_64" ]; then
  echo "缺少 system-images;android-35;google_apis;x86_64" >&2
  exit 1
fi
if [ ! -r /dev/kvm ] || [ ! -w /dev/kvm ]; then
  echo "当前用户读不了 /dev/kvm" >&2
  exit 1
fi

OLD_URL="https://github.com/kingshuoxu/LoRA-bge-long-memory/releases/download/android-v0.1.4/app-debug.apk"
OLD_SHA="be5e70e7eb228ad2a2ca720075aa01478f981734e2e1b0182111f55dd1dc467c"
curl -fL --retry 3 -o "$STAGE/app-0.1.4-published.apk" "$OLD_URL"
got=$(sha256sum "$STAGE/app-0.1.4-published.apk" | awk '{print $1}')
if [ "$got" != "$OLD_SHA" ]; then
  echo "已发布 0.1.4 的 SHA256 对不上: $got" >&2
  exit 1
fi
badging=$("$AAPT" dump badging "$STAGE/app-0.1.4-published.apk")
printf '%s\n' "$badging" | grep -q "versionCode='1004'"
printf '%s\n' "$badging" | grep -q "versionName='0.1.4'"
printf '%s\n' "$badging" | grep -q "native-code: 'arm64-v8a'"
python3 - "$STAGE/app-0.1.4-published.apk" "$STAGE/urls-in-0.1.4.txt" << 'PY'
import pathlib, re, sys, zipfile
blob = b""
with zipfile.ZipFile(sys.argv[1]) as zf:
    for name in zf.namelist():
        if name.startswith("classes") and name.endswith(".dex"):
            blob += zf.read(name)
text = blob.decode("latin1", errors="ignore")
hits = sorted(set(re.findall(r"https://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+", text)))
keep = [hit for hit in hits if "github" in hit or "ghproxy" in hit or "gh-proxy" in hit or "ghfast" in hit]
pathlib.Path(sys.argv[2]).write_text("\n".join(keep) + "\n", encoding="utf-8")
print("\n".join(keep))
PY

export ANDROID_AVD_HOME="/tmp/lorabge-inapp-avd"
rm -rf "$ANDROID_AVD_HOME"
mkdir -p "$ANDROID_AVD_HOME"
AVDMANAGER=$(find "$SDK/cmdline-tools" -path '*/bin/avdmanager' | head -1)
test -n "$AVDMANAGER"
if ! echo no | "$AVDMANAGER" create avd -n "$AVD" -k "system-images;android-35;google_apis;x86_64" --force >"$STAGE/avdmanager.log" 2>&1; then
  cat "$STAGE/avdmanager.log" >&2
  exit 1
fi
CFG="$ANDROID_AVD_HOME/${AVD}.avd/config.ini"
if [ ! -f "$CFG" ]; then
  FOUND=$(find "$HOME/.android" "$SDK" -path "*/${AVD}.avd/config.ini" 2>/dev/null | head -1 || true)
  if [ -n "$FOUND" ]; then
    mkdir -p "$ANDROID_AVD_HOME/${AVD}.avd"
    cp -a "$(dirname "$FOUND")/." "$ANDROID_AVD_HOME/${AVD}.avd/"
  fi
fi
test -f "$CFG"
python3 - "$CFG" << 'PY'
import pathlib, sys
path = pathlib.Path(sys.argv[1])
wanted = {
    "fastboot.forceColdBoot": "yes",
    "fastboot.forceFastBoot": "no",
    "firstboot.bootFromDownloadableSnapshot": "no",
    "firstboot.bootFromLocalSnapshot": "no",
    "hw.ramSize": "3072M",
    "hw.lcd.width": "1080",
    "hw.lcd.height": "2400",
    "hw.lcd.density": "420",
    "hw.keyboard": "yes",
    "skin.dynamic": "yes",
    "showDeviceFrame": "no",
}
drop = {"skin.name", "skin.path"}
seen = set()
lines = []
for line in path.read_text(encoding="utf-8").splitlines():
    key = line.split("=", 1)[0].strip()
    if key in drop:
        continue
    if key in wanted:
        lines.append(f"{key} = {wanted[key]}")
        seen.add(key)
    else:
        lines.append(line)
for key, value in wanted.items():
    if key not in seen:
        lines.append(f"{key} = {value}")
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY

cleanup() {
  if [ -n "${EMU_PID:-}" ]; then
    "$ADB" -s "emulator-$PORT" emu kill >/dev/null 2>&1 || true
    kill "$EMU_PID" >/dev/null 2>&1 || true
    wait "$EMU_PID" >/dev/null 2>&1 || true
  fi
  if [ -n "${LOG_PID:-}" ]; then
    kill "$LOG_PID" >/dev/null 2>&1 || true
    wait "$LOG_PID" >/dev/null 2>&1 || true
  fi
  if [ -n "${XVFB_PID:-}" ]; then
    kill "$XVFB_PID" >/dev/null 2>&1 || true
    wait "$XVFB_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

if ! command -v Xvfb >/dev/null 2>&1; then
  echo "缺少 Xvfb" >&2
  exit 1
fi
Xvfb :99 -screen 0 1280x2800x24 -ac +extension GLX +render -noreset >"$STAGE/xvfb.log" 2>&1 &
XVFB_PID=$!
export DISPLAY=:99

"$EMU" -avd "$AVD" -port "$PORT" -no-audio -no-boot-anim -no-snapshot -gpu swiftshader_indirect -memory 3072 -accel on -no-metrics -dns-server 8.8.8.8 >"$STAGE/emulator.log" 2>&1 &
EMU_PID=$!

i=0
boot=""
while [ "$i" -lt 240 ]; do
  if ! kill -0 "$EMU_PID" 2>/dev/null; then
    echo "模拟器退出了" >&2
    tail -40 "$STAGE/emulator.log" >&2 || true
    exit 1
  fi
  boot=$("$ADB" -s "emulator-$PORT" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r') || boot=""
  if [ "$boot" = "1" ]; then
    break
  fi
  i=$((i + 1))
  sleep 2
done
if [ "$boot" != "1" ]; then
  echo "模拟器没有在时限内启动" >&2
  tail -40 "$STAGE/emulator.log" >&2 || true
  exit 1
fi

"$ADB" -s "emulator-$PORT" logcat -c || true
"$ADB" -s "emulator-$PORT" logcat -v time >"$STAGE/logcat.txt" 2>&1 &
LOG_PID=$!

"$ADB" -s "emulator-$PORT" shell input keyevent 82 >/dev/null 2>&1 || true
"$ADB" -s "emulator-$PORT" shell settings put global device_provisioned 1 || true
"$ADB" -s "emulator-$PORT" shell settings put secure user_setup_complete 1 || true
"$ADB" -s "emulator-$PORT" shell settings put global package_verifier_enable 0 || true
"$ADB" -s "emulator-$PORT" shell settings put global verifier_verify_adb_installs 0 || true
"$ADB" -s "emulator-$PORT" shell pm disable-user --user 0 com.google.android.setupwizard >/dev/null 2>&1 || true

"$ADB" -s "emulator-$PORT" install -r -t "$STAGE/app-0.1.4-published.apk"
"$ADB" -s "emulator-$PORT" shell appops set com.lorabge.memory REQUEST_INSTALL_PACKAGES allow
"$ADB" -s "emulator-$PORT" shell getprop ro.product.cpu.abilist >"$STAGE/abilist.txt"
printf 'x\n' >"$STAGE/e2e-marker"
"$ADB" -s "emulator-$PORT" push "$STAGE/e2e-marker" /data/local/tmp/lorabge-e2e
"$ADB" -s "emulator-$PORT" shell run-as com.lorabge.memory mkdir -p files/setup
"$ADB" -s "emulator-$PORT" shell run-as com.lorabge.memory cp /data/local/tmp/lorabge-e2e files/setup/e2e

export ANDROID_SERIAL="emulator-$PORT"
export INAPP_STAGE="$STAGE"
export ADB
export PATH="$SDK/platform-tools:$PATH"
python3 "$ROOT/android/scripts/inapp_update_drive.py"
echo "in-app update 0.1.4 -> 0.1.5 finished"

#!/bin/sh
# 用同一把测试钥匙打 0.1.2 和 0.1.3 的 x86_64 包（不含 arm64 .so），
# 在模拟器上 adb install -r，确认记忆、模型和设置还在。
# 已发布的 0.1.2 是另一把钥匙，不能拿来做这次覆盖安装。
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
SDK=${ANDROID_SDK_ROOT:-${ANDROID_HOME:-/tmp/android-sdk}}
export ANDROID_SDK_ROOT="$SDK"
export ANDROID_HOME="$SDK"
PORT=${UPGRADE_PORT:-5574}
AVD=${UPGRADE_AVD:-lorabge-upgrade}
STAGE="$ROOT/android/out/upgrade"
mkdir -p "$STAGE"
ADB="$SDK/platform-tools/adb"
EMU="$SDK/emulator/emulator"
AAPT=$(find "$SDK/build-tools" -path '*/aapt' | sort | tail -1)
APKSIGNER=$(find "$SDK/build-tools" -path '*/apksigner' | sort | tail -1)
test -x "$ADB"
test -x "$EMU"
test -n "$AAPT"
test -n "$APKSIGNER"

if [ ! -d "$SDK/system-images/android-35/aosp_atd/x86_64" ]; then
  echo "缺少 system-images;android-35;aosp_atd;x86_64" >&2
  exit 1
fi

if [ -r /dev/kvm ] && [ -w /dev/kvm ]; then
  ACCEL=on
else
  echo "当前用户读不了 /dev/kvm。x86_64 模拟器没有硬件加速会直接退出。" >&2
  exit 1
fi

export ANDROID_AVD_HOME="$STAGE/avd-home"
rm -rf "$ANDROID_AVD_HOME"
mkdir -p "$ANDROID_AVD_HOME"
AVDMANAGER=$(find "$SDK/cmdline-tools" -path '*/bin/avdmanager' | head -1)
test -n "$AVDMANAGER"
if ! echo no | "$AVDMANAGER" create avd -n "$AVD" -k "system-images;android-35;aosp_atd;x86_64" --force >"$STAGE/avdmanager.log" 2>&1; then
  cat "$STAGE/avdmanager.log" >&2
  exit 1
fi
CFG="$ANDROID_AVD_HOME/${AVD}.avd/config.ini"
if [ ! -f "$CFG" ]; then
  FOUND=$(find "$HOME/.android" "$SDK" -path "*/${AVD}.avd/config.ini" 2>/dev/null | head -1 || true)
  if [ -n "$FOUND" ]; then
    mkdir -p "$ANDROID_AVD_HOME/${AVD}.avd"
    cp -a "$(dirname "$FOUND")/." "$ANDROID_AVD_HOME/${AVD}.avd/"
    INI=$(find "$HOME/.android" "$SDK" -name "${AVD}.ini" 2>/dev/null | head -1 || true)
    if [ -n "$INI" ]; then cp "$INI" "$ANDROID_AVD_HOME/${AVD}.ini"; fi
  fi
fi
if [ ! -f "$CFG" ]; then
  echo "avdmanager 没有写出 $CFG" >&2
  cat "$STAGE/avdmanager.log" >&2
  find "$ANDROID_AVD_HOME" "$HOME/.android" -name config.ini >&2 || true
  exit 1
fi
# aosp_atd 的模板会去拉启动快照，并且内存只有 96M。avdmanager 写成的键没有空格，模拟器重写时又会加上空格。
python3 - "$CFG" << 'PY'
import pathlib, sys
path = pathlib.Path(sys.argv[1])
wanted = {
    "fastboot.forceColdBoot": "yes",
    "fastboot.forceFastBoot": "no",
    "firstboot.bootFromDownloadableSnapshot": "no",
    "firstboot.bootFromLocalSnapshot": "no",
    "hw.ramSize": "2048M",
}
seen = set()
lines = []
for line in path.read_text(encoding="utf-8").splitlines():
    key = line.split("=", 1)[0].strip()
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
  "$ADB" -s "emulator-$PORT" emu kill >/dev/null 2>&1 || true
  if [ -n "${EMU_PID:-}" ]; then
    kill "$EMU_PID" >/dev/null 2>&1 || true
    wait "$EMU_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

"$EMU" -avd "$AVD" -port "$PORT" -no-window -no-audio -no-boot-anim -no-snapshot -no-snapshot-load -no-snapshot-save -wipe-data -gpu swiftshader_indirect -memory 2048 -accel "$ACCEL" -no-metrics >"$STAGE/emulator.log" 2>&1 &
EMU_PID=$!

cd "$ROOT/android/apk"
./gradlew assembleDebug -Plorabge.skipNative=true -Plorabge.versionName=0.1.2 --no-daemon
cp app/build/outputs/apk/debug/app-debug.apk "$STAGE/app-0.1.2.apk"
./gradlew assembleDebug -Plorabge.skipNative=true -Plorabge.versionName=0.1.3 --no-daemon
cp app/build/outputs/apk/debug/app-debug.apk "$STAGE/app-0.1.3.apk"

badging() {
  "$AAPT" dump badging "$1"
}
echo "$(badging "$STAGE/app-0.1.2.apk")" | grep -q "versionCode='1002'"
echo "$(badging "$STAGE/app-0.1.2.apk")" | grep -q "versionName='0.1.2'"
echo "$(badging "$STAGE/app-0.1.3.apk")" | grep -q "versionCode='1003'"
echo "$(badging "$STAGE/app-0.1.3.apk")" | grep -q "versionName='0.1.3'"
if unzip -l "$STAGE/app-0.1.3.apk" | grep -q '\.so$'; then
  echo "升级测试包不应带原生库，否则 x86_64 模拟器装不上" >&2
  exit 1
fi

CERT_A=$("$APKSIGNER" verify --print-certs "$STAGE/app-0.1.2.apk" | grep 'SHA-256 digest' | head -1)
CERT_B=$("$APKSIGNER" verify --print-certs "$STAGE/app-0.1.3.apk" | grep 'SHA-256 digest' | head -1)
test -n "$CERT_A"
test "$CERT_A" = "$CERT_B"

i=0
boot=""
while [ "$i" -lt 180 ]; do
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
"$ADB" -s "emulator-$PORT" shell input keyevent 82 >/dev/null 2>&1 || true

"$ADB" -s "emulator-$PORT" install -r -t "$STAGE/app-0.1.2.apk"
# adb shell 会把 run-as … sh -c "echo > file" 里的重定向吃掉，文件写不进应用目录。
printf '%s\n' 'keep-memory' >"$STAGE/keep.txt"
printf '%s\n' 'keep-model' >"$STAGE/keep.bin"
printf '%s\n' '<?xml version="1.0" encoding="utf-8" standalone="yes" ?>' '<map>' '<string name="keep">yes</string>' '</map>' >"$STAGE/setup.xml"
"$ADB" -s "emulator-$PORT" push "$STAGE/keep.txt" /data/local/tmp/lorabge-keep.txt
"$ADB" -s "emulator-$PORT" push "$STAGE/keep.bin" /data/local/tmp/lorabge-keep.bin
"$ADB" -s "emulator-$PORT" push "$STAGE/setup.xml" /data/local/tmp/lorabge-setup.xml
"$ADB" -s "emulator-$PORT" shell chmod 644 /data/local/tmp/lorabge-keep.txt /data/local/tmp/lorabge-keep.bin /data/local/tmp/lorabge-setup.xml
"$ADB" -s "emulator-$PORT" shell run-as com.lorabge.memory mkdir -p files/memory files/models shared_prefs
"$ADB" -s "emulator-$PORT" shell run-as com.lorabge.memory cp /data/local/tmp/lorabge-keep.txt files/memory/keep.txt
"$ADB" -s "emulator-$PORT" shell run-as com.lorabge.memory cp /data/local/tmp/lorabge-keep.bin files/models/keep.bin
"$ADB" -s "emulator-$PORT" shell run-as com.lorabge.memory cp /data/local/tmp/lorabge-setup.xml shared_prefs/setup.xml

"$ADB" -s "emulator-$PORT" install -r -t "$STAGE/app-0.1.3.apk"
MEM=$("$ADB" -s "emulator-$PORT" shell run-as com.lorabge.memory cat files/memory/keep.txt | tr -d '\r')
MOD=$("$ADB" -s "emulator-$PORT" shell run-as com.lorabge.memory cat files/models/keep.bin | tr -d '\r')
PREF=$("$ADB" -s "emulator-$PORT" shell run-as com.lorabge.memory cat shared_prefs/setup.xml | tr -d '\r')
CODE=$("$ADB" -s "emulator-$PORT" shell dumpsys package com.lorabge.memory | tr -d '\r' | sed -n 's/.*versionCode=\([0-9]*\).*/\1/p' | head -1)
printf '%s\n' "$MEM" | grep -qx 'keep-memory'
printf '%s\n' "$MOD" | grep -qx 'keep-model'
printf '%s\n' "$PREF" | grep -q 'name="keep">yes'
test "$CODE" = "1003"
echo "upgrade preserved memory, models, settings; versionCode 1003"

"$ADB" -s "emulator-$PORT" shell settings put secure show_ime_with_hard_keyboard 1
"$ADB" -s "emulator-$PORT" shell ime enable com.android.inputmethod.latin/.LatinIME || true
"$ADB" -s "emulator-$PORT" shell ime set com.android.inputmethod.latin/.LatinIME || true
export ANDROID_SERIAL="emulator-$PORT"
set +e
./gradlew connectedDebugAndroidTest -Plorabge.skipNative=true -Plorabge.e2eHooks=true -Plorabge.versionName=0.1.3 -Pandroid.testInstrumentationRunnerArguments.class=com.lorabge.memory.ChatFlowTest,com.lorabge.memory.NebulaGestureTest --no-daemon
gradle_status=$?
set -e
# aosp_atd 没有 tar。逐个 cat 出来。测试失败也要留下截图。
mkdir -p "$STAGE/shots" "$STAGE/shots/frames"
: >"$STAGE/e2e-ls.txt"
"$ADB" -s "emulator-$PORT" shell run-as com.lorabge.memory ls files/e2e >"$STAGE/e2e-ls.txt" || true
while IFS= read -r name; do
  name=$(printf '%s' "$name" | tr -d '\r')
  [ -n "$name" ] || continue
  if [ "$name" = "frames" ]; then
    "$ADB" -s "emulator-$PORT" shell run-as com.lorabge.memory ls files/e2e/frames >"$STAGE/frames-ls.txt" || true
    while IFS= read -r frame; do
      frame=$(printf '%s' "$frame" | tr -d '\r')
      [ -n "$frame" ] || continue
      "$ADB" -s "emulator-$PORT" exec-out run-as com.lorabge.memory cat "files/e2e/frames/$frame" >"$STAGE/shots/frames/$frame" || true
    done <"$STAGE/frames-ls.txt"
  else
    "$ADB" -s "emulator-$PORT" exec-out run-as com.lorabge.memory cat "files/e2e/$name" >"$STAGE/shots/$name" || true
  fi
done <"$STAGE/e2e-ls.txt"
if ls "$STAGE/shots/frames/"*.png >/dev/null 2>&1; then
  ffmpeg -y -framerate 2 -i "$STAGE/shots/frames/%04d.png" -vf "scale=trunc(iw/2)*2:trunc(ih/2)*2" -c:v libx264 -pix_fmt yuv420p -movflags +faststart "$STAGE/shots/nebula-gesture.mp4" || true
fi
if [ "$gradle_status" -ne 0 ]; then
  echo "仪器测试失败，已尽量保存截图和录像" >&2
  find "$STAGE/shots" -type f -exec ls -l {} \; >&2 || true
  exit "$gradle_status"
fi
for name in 01-ime.png 02-typing.png 03-ack.png 04-pending.png 05-train.png 06-recall-cat.png 07-zore.png 08-nebula-fact.png 09-nebula-before.png 10-nebula-after.png nebula-gesture.mp4 nebula-renderer.txt; do
  test -s "$STAGE/shots/$name"
done
grep -q '^path=' "$STAGE/shots/nebula-renderer.txt"
grep -q '^variance=' "$STAGE/shots/nebula-renderer.txt"
grep -q '^pixelDiff=' "$STAGE/shots/nebula-renderer.txt"
# 仪器测试包才允许带草稿注入。这里确认这次装上去的测试包带了它，发布包在 release workflow 里做相反的检查。
if ! unzip -p app/build/outputs/apk/debug/app-debug.apk 'classes*.dex' | grep -a -q 'e2e-draft.txt'; then
  echo "仪器测试包缺少 e2e-draft.txt，中文句子不会进输入框" >&2
  exit 1
fi
mp4_bytes=$(wc -c <"$STAGE/shots/nebula-gesture.mp4" | tr -d '[:space:]')
test "$mp4_bytes" -gt 8000
echo "nebula renderer:"
cat "$STAGE/shots/nebula-renderer.txt"
echo "emulator chat flow and nebula gestures saved"

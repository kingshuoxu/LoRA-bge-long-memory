#!/bin/sh
# 用同一把测试钥匙打 0.1.15 和 0.1.16 的 x86_64 包（不含 arm64 .so），
# 在模拟器上 adb install -r，确认记忆、模型和设置还在。
# 已发布的 0.1.4 走应用内「检查更新」升到 0.1.5，那条在 inapp_update_014_to_015.sh，不在这里。
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
    "hw.lcd.width": "1080",
    "hw.lcd.height": "2400",
    "hw.lcd.density": "420",
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
  if [ -n "${HOST_PID:-}" ]; then
    kill -INT "$HOST_PID" >/dev/null 2>&1 || true
    wait "$HOST_PID" >/dev/null 2>&1 || true
  fi
  "$ADB" -s "emulator-$PORT" emu kill >/dev/null 2>&1 || true
  if [ -n "${EMU_PID:-}" ]; then
    kill "$EMU_PID" >/dev/null 2>&1 || true
    wait "$EMU_PID" >/dev/null 2>&1 || true
  fi
  if [ -n "${XVFB_PID:-}" ]; then
    kill "$XVFB_PID" >/dev/null 2>&1 || true
    wait "$XVFB_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

# -no-window 时控制台 screenrecord 和 UiAutomation 都是一块黑的 1080×2400，SwiftShader 没画进那张缓冲。
# 开一个虚拟屏，让模拟器窗口把同一路画面合成出来，再用 x11grab 和 screenrecord 两路取像素。
if ! command -v Xvfb >/dev/null 2>&1; then
  echo "缺少 Xvfb" >&2
  exit 1
fi
Xvfb :99 -screen 0 1280x2800x24 -ac +extension GLX +render -noreset >"$STAGE/xvfb.log" 2>&1 &
XVFB_PID=$!
export DISPLAY=:99

"$EMU" -avd "$AVD" -port "$PORT" -no-audio -no-boot-anim -no-snapshot -no-snapshot-load -no-snapshot-save -wipe-data -gpu swiftshader_indirect -memory 2048 -accel "$ACCEL" -no-metrics >"$STAGE/emulator.log" 2>&1 &
EMU_PID=$!

cd "$ROOT/android/apk"
./gradlew assembleDebug -Plorabge.skipNative=true -Plorabge.versionName=0.1.15 --no-daemon
cp app/build/outputs/apk/debug/app-debug.apk "$STAGE/app-0.1.15.apk"
./gradlew assembleDebug -Plorabge.skipNative=true -Plorabge.versionName=0.1.16 --no-daemon
cp app/build/outputs/apk/debug/app-debug.apk "$STAGE/app-0.1.16.apk"

badging() {
  "$AAPT" dump badging "$1"
}
echo "$(badging "$STAGE/app-0.1.15.apk")" | grep -q "versionCode='1015'"
echo "$(badging "$STAGE/app-0.1.15.apk")" | grep -q "versionName='0.1.15'"
echo "$(badging "$STAGE/app-0.1.16.apk")" | grep -q "versionCode='1016'"
echo "$(badging "$STAGE/app-0.1.16.apk")" | grep -q "versionName='0.1.16'"
if unzip -l "$STAGE/app-0.1.16.apk" | grep -q '\.so$'; then
  echo "升级测试包不应带原生库，否则 x86_64 模拟器装不上" >&2
  exit 1
fi

CERT_A=$("$APKSIGNER" verify --print-certs "$STAGE/app-0.1.15.apk" | grep 'SHA-256 digest' | head -1)
CERT_B=$("$APKSIGNER" verify --print-certs "$STAGE/app-0.1.16.apk" | grep 'SHA-256 digest' | head -1)
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
sleep 2
DISPLAY=:99 xwininfo -root -tree >"$STAGE/xwin.txt" 2>/dev/null || true
python3 - "$STAGE/xwin.txt" "$STAGE/grab.env" << 'PY'
import pathlib, re, sys
text = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace") if pathlib.Path(sys.argv[1]).exists() else ""
root = re.search(r"Width:\s*(\d+)\s+Height:\s*(\d+)", text)
if root:
    w, h, x, y = int(root.group(1)), int(root.group(2)), 0, 0
else:
    best = None
    for match in re.finditer(r"(\d+)x(\d+)\+(\d+)\+(\d+)", text):
        w, h, x, y = (int(part) for part in match.groups())
        if w < 200 or h < 400 or w > 1280 or h > 2800:
            continue
        if best is None or w * h > best[0] * best[1]:
            best = (w, h, x, y)
    if best is None:
        best = (1280, 2800, 0, 0)
    w, h, x, y = best
w -= w % 2
h -= h % 2
pathlib.Path(sys.argv[2]).write_text(
    f"GRAB_SIZE={w}x{h}\nGRAB_INPUT=:99.0+{x},{y}\n",
    encoding="utf-8",
)
print(f"host grab {w}x{h}+{x}+{y}")
PY
# shellcheck disable=SC1091
. "$STAGE/grab.env"

"$ADB" -s "emulator-$PORT" install -r -t "$STAGE/app-0.1.15.apk"
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

"$ADB" -s "emulator-$PORT" install -r -t "$STAGE/app-0.1.16.apk"
MEM=$("$ADB" -s "emulator-$PORT" shell run-as com.lorabge.memory cat files/memory/keep.txt | tr -d '\r')
MOD=$("$ADB" -s "emulator-$PORT" shell run-as com.lorabge.memory cat files/models/keep.bin | tr -d '\r')
PREF=$("$ADB" -s "emulator-$PORT" shell run-as com.lorabge.memory cat shared_prefs/setup.xml | tr -d '\r')
CODE=$("$ADB" -s "emulator-$PORT" shell dumpsys package com.lorabge.memory | tr -d '\r' | sed -n 's/.*versionCode=\([0-9]*\).*/\1/p' | head -1)
printf '%s\n' "$MEM" | grep -qx 'keep-memory'
printf '%s\n' "$MOD" | grep -qx 'keep-model'
printf '%s\n' "$PREF" | grep -q 'name="keep">yes'
test "$CODE" = "1016"
echo "upgrade preserved memory, models, settings; versionCode 1016"

"$ADB" -s "emulator-$PORT" shell settings put secure show_ime_with_hard_keyboard 1
"$ADB" -s "emulator-$PORT" shell ime enable com.android.inputmethod.latin/.LatinIME || true
"$ADB" -s "emulator-$PORT" shell ime set com.android.inputmethod.latin/.LatinIME || true
export ANDROID_SERIAL="emulator-$PORT"
# POSIX sh 没有 $'\x89PNG'。签名用 od 认，避免把真 PNG 丢掉。
png_file() {
  sig=$(od -An -t x1 -N 4 "$1" 2>/dev/null | tr -d ' \n')
  [ "$sig" = "89504e47" ]
}
# 仪器测试结束时 Gradle 会卸掉应用，应用私有目录里的截图一起没了。测试还在跑的时候就往外拷。
# ffmpeg 和 adb 默认读标准输入。这个循环正用标准输入送文件名，不隔开会把后面的 canvas-*.png 和 nebula-renderer.txt 吃掉。
pull_e2e() {
  mkdir -p "$STAGE/shots" "$STAGE/shots/frames"
  if ! "$ADB" -s "emulator-$PORT" shell run-as com.lorabge.memory ls -1 files/e2e >"$STAGE/e2e-ls.txt" 2>/dev/null; then
    return 0
  fi
  while IFS= read -r name; do
    name=$(printf '%s' "$name" | tr -d '\r')
    [ -n "$name" ] || continue
    case "$name" in
      *" "*|*"run-as"*) continue ;;
    esac
    if [ "$name" = "frames" ]; then
      "$ADB" -s "emulator-$PORT" shell run-as com.lorabge.memory ls -1 files/e2e/frames >"$STAGE/frames-ls.txt" </dev/null 2>/dev/null || true
      while IFS= read -r frame; do
        frame=$(printf '%s' "$frame" | tr -d '\r')
        [ -n "$frame" ] || continue
        tmp="$STAGE/shots/frames/.incoming"
        "$ADB" -s "emulator-$PORT" exec-out run-as com.lorabge.memory cat "files/e2e/frames/$frame" >"$tmp" </dev/null || true
        if [ -s "$tmp" ] && ! head -c 16 "$tmp" | grep -q 'run-as:' && png_file "$tmp"; then
          mv "$tmp" "$STAGE/shots/frames/$frame"
        else
          rm -f "$tmp"
        fi
      done <"$STAGE/frames-ls.txt"
    else
      tmp="$STAGE/shots/.incoming"
      "$ADB" -s "emulator-$PORT" exec-out run-as com.lorabge.memory cat "files/e2e/$name" >"$tmp" </dev/null || true
      good=0
      if [ -s "$tmp" ] && ! head -c 64 "$tmp" | grep -q 'run-as:'; then
        case "$name" in
          *.png)
            if png_file "$tmp"; then
              good=1
            fi
            ;;
          *)
            good=1
            ;;
        esac
      fi
      if [ "$good" = 1 ]; then
        mv "$tmp" "$STAGE/shots/$name"
        if [ "$name" = "nebula-renderer.txt" ] && grep -q '^path=' "$STAGE/shots/$name"; then
          cp "$STAGE/shots/$name" "$STAGE/nebula-renderer.keep"
        fi
      else
        rm -f "$tmp"
      fi
      case "$name" in
        canvas-*.png) ;;
        *.png)
          if [ "$good" = 1 ] && [ -n "${GRAB_SIZE:-}" ] && [ ! -s "$STAGE/shots/$name.host.png" ]; then
            ffmpeg -nostdin -y -v error -f x11grab -video_size "$GRAB_SIZE" -i "$GRAB_INPUT" -frames:v 1 "$STAGE/shots/$name.host.png" </dev/null \
              && cp "$STAGE/shots/$name.host.png" "$STAGE/shots/$name" || true
          elif [ -s "$STAGE/shots/$name.host.png" ] && ! png_file "$STAGE/shots/$name"; then
            cp "$STAGE/shots/$name.host.png" "$STAGE/shots/$name"
          fi
          ;;
      esac
    fi
  done <"$STAGE/e2e-ls.txt"
}
set +e
./gradlew connectedDebugAndroidTest -Plorabge.skipNative=true -Plorabge.e2eHooks=true -Plorabge.versionName=0.1.16 -Pandroid.injected.androidTest.leaveApksInstalledAfterRun=true -Pandroid.testInstrumentationRunnerArguments.class=com.lorabge.memory.ChatFlowTest --no-daemon &
chat_pid=$!
set -e
while kill -0 "$chat_pid" 2>/dev/null; do
  pull_e2e || true
  sleep 3
done
set +e
wait "$chat_pid"
chat_status=$?
set -e
pull_e2e || true
if [ "$chat_status" -ne 0 ]; then
  echo "对话流程失败" >&2
fi
# 星云单独跑。UiAutomation.takeScreenshot 在 aosp_atd 上只有 WebView 的纯色底，没有 GL。
# 等测试写好 nebula-ready，再用模拟器控制台录物理画面，这一路包含 SwiftShader 画出来的像素。
# 录像写到绝对路径。相对文件名会落在模拟器进程的工作目录，不在 AVD 目录里。
RECORD="$STAGE/nebula-gesture.webm"
RECORD_NAME="$RECORD"
set +e
./gradlew connectedDebugAndroidTest -Plorabge.skipNative=true -Plorabge.e2eHooks=true -Plorabge.versionName=0.1.16 -Pandroid.injected.androidTest.leaveApksInstalledAfterRun=true -Pandroid.testInstrumentationRunnerArguments.class=com.lorabge.memory.NebulaGestureTest --no-daemon &
nebula_pid=$!
recorded=0
for _ in $(seq 1 180); do
  pull_e2e || true
  if [ "$recorded" = 0 ] && "$ADB" -s "emulator-$PORT" shell run-as com.lorabge.memory ls files/e2e/nebula-ready >/dev/null 2>&1; then
    "$ADB" -s "emulator-$PORT" emu screenrecord start "$RECORD" >"$STAGE/screenrecord-start.txt" 2>&1 || true
    if ! grep -q OK "$STAGE/screenrecord-start.txt"; then
      RECORD_NAME="nebula-gesture.webm"
      "$ADB" -s "emulator-$PORT" emu screenrecord start "$RECORD_NAME" >"$STAGE/screenrecord-start.txt" 2>&1 || true
    fi
    if [ -n "${GRAB_SIZE:-}" ]; then
      ffmpeg -nostdin -y -f x11grab -framerate 8 -video_size "$GRAB_SIZE" -i "$GRAB_INPUT" \
        -c:v libx264 -pix_fmt yuv420p -movflags +faststart "$STAGE/nebula-host.mp4" </dev/null >"$STAGE/x11grab.log" 2>&1 &
      HOST_PID=$!
    fi
    recorded=1
  fi
  if ! kill -0 "$nebula_pid" 2>/dev/null; then
    break
  fi
  sleep 1
done
wait "$nebula_pid"
nebula_status=$?
if [ "$recorded" = 1 ]; then
  "$ADB" -s "emulator-$PORT" emu screenrecord stop "$RECORD_NAME" >"$STAGE/screenrecord-stop.txt" 2>&1 || true
  sleep 2
fi
if [ -n "${HOST_PID:-}" ]; then
  kill -INT "$HOST_PID" >/dev/null 2>&1 || true
  wait "$HOST_PID" >/dev/null 2>&1 || true
  HOST_PID=""
fi
set -e
pull_e2e || true
if [ "$chat_status" -ne 0 ]; then
  gradle_status=$chat_status
else
  gradle_status=$nebula_status
fi
if ls "$STAGE/shots/frames/"*.png >/dev/null 2>&1; then
  ffmpeg -nostdin -y -framerate 2 -i "$STAGE/shots/frames/%04d.png" -vf "scale=trunc(iw/2)*2:trunc(ih/2)*2" -c:v libx264 -pix_fmt yuv420p -movflags +faststart "$STAGE/shots/nebula-gesture.mp4" </dev/null || true
fi
WEBM=""
if [ -s "$RECORD" ]; then
  WEBM="$RECORD"
elif [ -s "$ROOT/nebula-gesture.webm" ]; then
  WEBM="$ROOT/nebula-gesture.webm"
elif [ -s "$ROOT/android/apk/nebula-gesture.webm" ]; then
  WEBM="$ROOT/android/apk/nebula-gesture.webm"
else
  WEBM=$(find "$STAGE" "$ANDROID_AVD_HOME" "$HOME/.android" -name 'nebula-gesture.webm' -size +1k 2>/dev/null | head -1 || true)
fi
if [ -n "$WEBM" ] && [ -s "$WEBM" ]; then
  cp "$WEBM" "$STAGE/shots/nebula-gesture.webm"
fi
if [ -s "$STAGE/nebula-host.mp4" ]; then
  cp "$STAGE/nebula-host.mp4" "$STAGE/shots/nebula-host.mp4"
fi
# 星云像素以画布 readPixels 为准。模拟器窗口大多是灰边，不能拿来当手势证据。
CANVAS="$STAGE/shots/nebula-canvas.mp4"
if [ -s "$STAGE/shots/canvas-before.png" ] && [ -s "$STAGE/shots/canvas-after.png" ]; then
  ffmpeg -nostdin -y -v error -loop 1 -t 1 -i "$STAGE/shots/canvas-before.png" -loop 1 -t 1 -i "$STAGE/shots/canvas-after.png" \
    -filter_complex "[0:v]scale=160:220:flags=neighbor,setsar=1[a];[1:v]scale=160:220:flags=neighbor,setsar=1[b];[a][b]concat=n=2:v=1:a=0" \
    -c:v libx264 -pix_fmt yuv420p -movflags +faststart "$CANVAS" || true
fi
if [ -s "$STAGE/xwin.txt" ]; then
  cp "$STAGE/xwin.txt" "$STAGE/shots/xwin.txt" || true
fi
python3 - "$STAGE/shots/nebula-pixels.txt" "$STAGE/shots/nebula-gesture.mp4" "$CANVAS" "$WEBM" "$STAGE/nebula-host.mp4" << 'PY'
import pathlib, subprocess, sys
report_path, mp4_path, *videos = sys.argv[1:]

def score(path):
    probe = subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", path,
    ], text=True).strip()
    width, height = (int(part) for part in probe.split("x"))
    crop_w = max(2, width * 7 // 10)
    crop_h = max(2, height * 5 // 10)
    crop_x = max(0, (width - crop_w) // 2)
    crop_y = max(0, height * 18 // 100)
    raw = subprocess.check_output([
        "ffmpeg", "-v", "error", "-i", path,
        "-vf", f"fps=2,crop={crop_w}:{crop_h}:{crop_x}:{crop_y}",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ])
    frame_bytes = crop_w * crop_h * 3
    count = len(raw) // frame_bytes
    if count < 2:
        return f"source={path}\nframes={count}\nvariance=0\npixelDiff=0\nwidth={width}\nheight={height}\n", False

    def metrics(buf):
        step = 6 * 3
        values = []
        total = 0
        for index in range(0, len(buf) - 2, step):
            luma = (buf[index] + buf[index + 1] + buf[index + 2]) / 3
            values.append(luma)
            total += luma
        mean = total / max(1, len(values))
        var = sum((value - mean) ** 2 for value in values) / max(1, len(values) - 1)
        return var

    def diff(a, b):
        step = 6 * 3
        total = 0
        samples = 0
        for index in range(0, min(len(a), len(b)) - 2, step):
            total += abs(a[index] - b[index]) + abs(a[index + 1] - b[index + 1]) + abs(a[index + 2] - b[index + 2])
            samples += 1
        return total / max(1, samples)

    frames = [raw[i * frame_bytes:(i + 1) * frame_bytes] for i in range(count)]
    best = max(metrics(frame) for frame in frames)
    spread = max(diff(frames[0], frame) for frame in frames[1:])
    ok = best > 6 and spread > 2
    text = (
        f"source={path}\nframes={count}\nvariance={best:.2f}\npixelDiff={spread:.2f}\n"
        f"width={width}\nheight={height}\n"
    )
    return text, ok

chosen = ""
chunks = []
for index, video in enumerate(videos):
    path = pathlib.Path(video)
    if not path.is_file() or path.stat().st_size < 400:
        chunks.append(f"source={video}\nmissing=1\n")
        continue
    try:
        text, ok = score(str(path))
    except subprocess.CalledProcessError as ex:
        chunks.append(f"source={video}\nerror={ex}\n")
        continue
    chunks.append(text + f"ok={int(ok)}\n")
    if ok and index == 0 and not chosen:
        chosen = str(path)
report = "".join(chunks)
if chosen:
    subprocess.check_call([
        "ffmpeg", "-y", "-i", chosen,
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        mp4_path,
    ])
    report += f"chosen={chosen}\n"
else:
    report += "chosen=\n"
pathlib.Path(report_path).write_text(report, encoding="utf-8")
print(report)
if not chosen:
    raise SystemExit("nebula capture is flat or still")
PY
if [ "$gradle_status" -ne 0 ]; then
  echo "仪器测试失败，已尽量保存截图和录像" >&2
  find "$STAGE/shots" -type f -exec ls -l {} \; >&2 || true
  exit "$gradle_status"
fi
if [ -s "$STAGE/nebula-renderer.keep" ] && ! grep -q '^path=' "$STAGE/shots/nebula-renderer.txt" 2>/dev/null; then
  cp "$STAGE/nebula-renderer.keep" "$STAGE/shots/nebula-renderer.txt"
fi
for name in 01-ime.png 02-typing.png 03-ack.png 04-pending.png 05-train.png 06-recall-cat.png 07-zore.png 08-nebula-fact.png 09-nebula-before.png 10-nebula-after.png canvas-before.png canvas-after.png canvas-sky.png nebula-gesture.mp4 nebula-renderer.txt; do
  if [ ! -s "$STAGE/shots/$name" ]; then
    echo "缺少 $STAGE/shots/$name" >&2
    find "$STAGE/shots" -type f -exec ls -l {} \; >&2 || true
    exit 1
  fi
done
grep -q '^path=' "$STAGE/shots/nebula-renderer.txt"
grep -q '^variance=' "$STAGE/shots/nebula-renderer.txt"
grep -q '^pixelDiff=' "$STAGE/shots/nebula-renderer.txt"
test -s "$STAGE/shots/nebula-pixels.txt"
grep -q '^variance=' "$STAGE/shots/nebula-pixels.txt"
grep -q '^pixelDiff=' "$STAGE/shots/nebula-pixels.txt"
# 仪器测试包才允许带草稿注入。这里确认这次装上去的测试包带了它，发布包在 release workflow 里做相反的检查。
if ! unzip -p app/build/outputs/apk/debug/app-debug.apk 'classes*.dex' | grep -a -q 'e2e-draft.txt'; then
  echo "仪器测试包缺少 e2e-draft.txt，中文句子不会进输入框" >&2
  exit 1
fi
mp4_bytes=$(wc -c <"$STAGE/shots/nebula-gesture.mp4" | tr -d '[:space:]')
test "$mp4_bytes" -gt 1200
echo "nebula renderer:"
cat "$STAGE/shots/nebula-renderer.txt"
echo "emulator chat flow and nebula gestures saved"

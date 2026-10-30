#!/bin/sh
# 在已打开 USB 调试的手机上安装 APK,跑一次真实巩固训练,并打印耗时、内存、温度和回忆。
# 输出里的 benchmark.json 带 device:厂商、型号、SoC、GPU、后端、线程,以及 GPU/CPU 的预填充和解码 tok/s、Vulkan 设备名、驱动、子组宽度和特性。
# 用法: 手机连上电脑后执行
#   sh android/phone/run_device_benchmark.sh
# 需要本机已有 Qwen2.5-0.5B-Instruct 的 safetensors,以及 f16 对话基座和 bge。
# 训练大约是几十条样本、每个 epoch 4 步、共 4 个 epoch。把整段输出贴回来即可。
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
ADB=${ADB:-adb}
if [ -n "${ANDROID_SERIAL:-}" ]; then
  ADB="$ADB -s $ANDROID_SERIAL"
fi
PKG=com.lorabge.memory
APK=${APK:-$ROOT/android/apk/app/build/outputs/apk/debug/app-debug.apk}
if [ ! -f "$APK" ]; then
  echo "找不到 APK: $APK" >&2
  echo "先编 android/trainer/build_android.sh、android/qvac/build_android.sh,再在 android/apk 里 ./gradlew assembleDebug。" >&2
  exit 1
fi
$ADB get-state >/dev/null
$ADB install -r "$APK"
# 外部目录在较新的系统上 adb 写不进去。调试包用 run-as 写到应用私有目录。
MODEL=${MODEL_DIR:-$ROOT/models/Qwen2.5-0.5B-Instruct}
BASE=${BASE:-$ROOT/android/out/gguf/qwen2.5-0.5b-instruct-f16.gguf}
BGE=${BGE:-$ROOT/android/out/gguf/bge-small-zh-v1.5-f16.gguf}
copy_in() {
  src=$1
  dest=$2
  if [ ! -f "$src" ]; then
    echo "跳过,本机没有 $src"
    return
  fi
  echo "推送 $(basename "$src")"
  $ADB push "$src" /data/local/tmp/lorabge-one
  $ADB shell "mkdir -p files/$(dirname "$dest")" >/dev/null 2>&1 || true
  $ADB shell "run-as $PKG mkdir -p files/$(dirname "$dest")"
  $ADB shell "cat /data/local/tmp/lorabge-one | run-as $PKG sh -c 'cat > files/$dest'"
}
if [ -d "$MODEL" ]; then
  for name in config.json tokenizer.json tokenizer_config.json vocab.json merges.txt model.safetensors generation_config.json; do
    copy_in "$MODEL/$name" "models/Qwen2.5-0.5B-Instruct/$name"
  done
else
  echo "没有 $MODEL。训练读的是 safetensors,不是 GGUF。"
fi
copy_in "$BASE" "models/base.gguf"
copy_in "$BGE" "models/bge.gguf"
# 应用把对话模型放在外部 files/models。私有目录里的副本由基准启动时再认一次。
$ADB shell am force-stop "$PKG" || true
$ADB shell am start -n "$PKG/.MainActivity" --es mode benchmark
echo "已启动巩固基准。每 20 秒看一次状态,训练结束会打印 benchmark.json。"
seen=0
while [ "$seen" -lt 720 ]; do
  seen=$((seen + 1))
  raw=$($ADB shell "run-as $PKG cat files/memory/train/benchmark.json" 2>/dev/null || true)
  if printf '%s' "$raw" | grep -q '"wall_s"'; then
    echo "----- benchmark.json -----"
    printf '%s\n' "$raw"
    echo "----- telemetry.tsv -----"
    $ADB shell "run-as $PKG cat files/memory/train/telemetry.tsv" || true
    echo "----- 日志末尾 -----"
    $ADB shell "run-as $PKG tail -n 30 files/memory/train/train.log" || true
    exit 0
  fi
  state=$($ADB shell "run-as $PKG cat files/memory/train/status.json" 2>/dev/null || true)
  echo "[$seen] ${state:-等待任务}"
  if printf '%s' "$state" | grep -q '"state":"error"'; then
    echo "训练失败。" >&2
    $ADB shell "run-as $PKG tail -n 40 files/memory/train/train.log" || true
    exit 1
  fi
  sleep 20
done
echo "四小时内没有写完 benchmark.json。" >&2
exit 1

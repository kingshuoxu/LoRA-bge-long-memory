#!/bin/sh
# 从电脑把基座、bge、已有专家和 APK 推到小米 15。
# 用法: 手机打开 USB 调试,然后 sh android/phone/push_adb.sh
# 专家包先在桌面生成: python android/scripts/export_phone_bundle.py
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
SERIAL=${ANDROID_SERIAL:-}
ADB=${ADB:-adb}
if [ -n "$SERIAL" ]; then
  ADB="$ADB -s $SERIAL"
fi
PKG=com.lorabge.memory
DEST=/sdcard/Android/data/$PKG/files
APK=$ROOT/android/apk/app/build/outputs/apk/debug/app-debug.apk
if [ -f "$APK" ]; then
  $ADB install -r "$APK"
else
  echo "还没有 APK。先在 android/apk 里执行 download_qvac.sh 和 ./gradlew assembleDebug。"
fi
# 安装之后应用外部目录才存在。这里直接建目录,不依赖先点开应用。
$ADB shell mkdir -p "$DEST/models" "$DEST/import"
BASE=${BASE:-$ROOT/android/out/gguf/qwen2.5-0.5b-instruct-f16.gguf}
BGE=${BGE:-$ROOT/android/out/gguf/bge-small-zh-v1.5-f16.gguf}
if [ -f "$BASE" ]; then
  $ADB push "$BASE" "$DEST/models/base.gguf"
fi
if [ -f "$BGE" ]; then
  $ADB push "$BGE" "$DEST/models/bge.gguf"
fi
TRAIN_BASE=${TRAIN_BASE:-$ROOT/models/qwen2.5-0.5b-instruct-q8_0.gguf}
if [ -f "$TRAIN_BASE" ]; then
  $ADB push "$TRAIN_BASE" "$DEST/models/train_base.gguf"
fi
BUNDLE=${BUNDLE:-$ROOT/android/out/phone-bundle}
if [ -f "$BUNDLE/router.jsonl" ]; then
  $ADB push "$BUNDLE/router.jsonl" "$DEST/import/router.jsonl"
  if [ -f "$BUNDLE/fact_gate.json" ]; then
    $ADB push "$BUNDLE/fact_gate.json" "$DEST/import/fact_gate.json"
  fi
  for d in "$BUNDLE"/expert_*; do
    [ -d "$d" ] || continue
    name=$(basename "$d")
    $ADB shell mkdir -p "$DEST/import/$name"
    $ADB push "$d/." "$DEST/import/$name/"
  done
  echo "已推送完整专家包(router.jsonl、fact_memory、float32 向量、GGUF)。"
else
  echo "没有 phone-bundle。只推了 GGUF 适配器,应用导入还需要 router.jsonl 和向量。先跑 export_phone_bundle.py。"
  if [ -d "$ROOT/android/out/gguf" ]; then
    for f in "$ROOT"/android/out/gguf/expert_*.gguf; do
      [ -f "$f" ] || continue
      name=$(basename "$f" .gguf)
      $ADB shell mkdir -p "$DEST/import/$name"
      $ADB push "$f" "$DEST/import/$name/adapter.gguf"
    done
  fi
fi
echo "推送完成。打开「长期记忆」。基座和 bge 在 $DEST/models/。"
echo "专家页点「导入已推送的专家」。新对话会走这些记忆。应用内训练写到应用私有目录。"

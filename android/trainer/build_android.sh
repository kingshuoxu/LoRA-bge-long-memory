#!/bin/sh
# 把钉住的 MobileFineTuner 编成 arm64 训练程序,放进 APK 的 jniLibs。
# 提交 086b1a027fe708d5eaca89b1ec2bf1a876fb80de,补丁打开 FFN LoRA、事实 JSONL 和 GGUF 导出。
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")"/../.. && pwd)
PATCH=$ROOT/android/trainer/mft-ffn-lora.patch
COMMIT=086b1a027fe708d5eaca89b1ec2bf1a876fb80de
SRC=${MFT_SRC:-/tmp/MobileFineTuner-android}
DEST=$ROOT/android/apk/app/src/main/jniLibs/arm64-v8a
NDK=${ANDROID_NDK_ROOT:-${ANDROID_NDK_HOME:-}}
if [ -z "$NDK" ] && [ -n "${ANDROID_HOME:-}" ] && [ -d "$ANDROID_HOME/ndk" ]; then
  NDK=$(find "$ANDROID_HOME/ndk" -maxdepth 1 -mindepth 1 -type d | sort | tail -n 1)
fi
if [ -z "$NDK" ] || [ ! -f "$NDK/build/cmake/android.toolchain.cmake" ]; then
  echo "找不到 Android NDK。设置 ANDROID_NDK_ROOT。" >&2
  exit 1
fi
if [ ! -d "$SRC/.git" ]; then
  git clone --filter=blob:none https://github.com/Edge-Intelligence-Lab/MobileFineTuner.git "$SRC"
fi
git -C "$SRC" fetch --depth 1 origin "$COMMIT"
git -C "$SRC" checkout --detach "$COMMIT"
git -C "$SRC" apply --check "$PATCH"
git -C "$SRC" apply "$PATCH"
cmake -S "$SRC/examples/qwen_lora_finetune" -B "$SRC/examples/qwen_lora_finetune/build-android" \
  -DCMAKE_TOOLCHAIN_FILE="$NDK/build/cmake/android.toolchain.cmake" \
  -DANDROID_ABI=arm64-v8a \
  -DANDROID_PLATFORM=android-29 \
  -DANDROID_STL=c++_static \
  -DCMAKE_BUILD_TYPE=Release \
  -DUSE_BLAS=OFF
cmake --build "$SRC/examples/qwen_lora_finetune/build-android" --target train_wikitext -j"${JOBS:-4}"
mkdir -p "$DEST"
cp "$SRC/examples/qwen_lora_finetune/build-android/train_wikitext" "$DEST/libtrain-mft.so"
STRIP=$(find "$NDK/toolchains/llvm/prebuilt" -name llvm-strip | head -1)
if [ -n "$STRIP" ]; then
  "$STRIP" "$DEST/libtrain-mft.so"
fi
chmod 755 "$DEST/libtrain-mft.so"
echo "已放入 $DEST/libtrain-mft.so"

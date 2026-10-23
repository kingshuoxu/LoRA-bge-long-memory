#!/bin/sh
# 用和桌面同一份 QVAC 源码编 Android arm64 的 libllama。
# 提交 b73e75af5,再打上 bert-bge-cased 补丁,这样大写词不会被 WPM 折成小写。
# 优先打开 Vulkan,小米 15 的 Adreno 830 走这条。着色器工具链编不过时退回 CPU,并在日志里写明。
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")"/../.. && pwd)
COMMIT=b73e75af5f2ab69c0e8984637c743c6a50ebc98d
PATCH=$ROOT/android/qvac/wpm-cased.patch
SRC=${QVAC_SRC:-/tmp/qvac-android}
DEST=$ROOT/android/apk/app/src/main/jniLibs/arm64-v8a
NDK=${ANDROID_NDK_ROOT:-${ANDROID_NDK_HOME:-}}
if [ -z "$NDK" ] && [ -n "${ANDROID_HOME:-}" ] && [ -d "$ANDROID_HOME/ndk" ]; then
  NDK=$(find "$ANDROID_HOME/ndk" -maxdepth 1 -mindepth 1 -type d | sort | tail -n 1)
fi
if [ -z "$NDK" ] || [ ! -f "$NDK/build/cmake/android.toolchain.cmake" ]; then
  echo "找不到 Android NDK。设置 ANDROID_NDK_ROOT。" >&2
  exit 1
fi
if [ ! -e "$SRC/.git" ]; then
  git clone --filter=blob:none https://github.com/tether-ai-research/qvac-fabric-llm-finetune.git "$SRC"
fi
git -C "$SRC" fetch --depth 1 origin "$COMMIT"
git -C "$SRC" reset --hard "$COMMIT"
git -C "$SRC" clean -fd -e build-android
git -C "$SRC" apply --check "$PATCH"
git -C "$SRC" apply "$PATCH"
if ! command -v glslc >/dev/null 2>&1 || [ ! -f /usr/include/vulkan/vulkan.hpp ]; then
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update -qq && apt-get install -y -qq glslc libvulkan-dev || true
  fi
fi
# NDK 只有 vulkan.h。Vulkan-Hpp 放在 idirafter,这样 vulkan.h 仍用安卓那份。
HPP=/tmp/vulkan-hpp
if [ -f /usr/include/vulkan/vulkan.hpp ]; then
  rm -rf "$HPP"
  mkdir -p "$HPP"
  cp -a /usr/include/vulkan "$HPP/vulkan"
fi
HPP_FLAG=""
if [ -d "$HPP/vulkan" ]; then
  HPP_FLAG="-idirafter $HPP"
fi
STRIP=$(find "$NDK/toolchains/llvm/prebuilt" -name llvm-strip | head -1)
build_one() {
  vulkan=$1
  dir=$SRC/build-android
  rm -rf "$dir"
  cmake -S "$SRC" -B "$dir" \
    -DCMAKE_TOOLCHAIN_FILE="$NDK/build/cmake/android.toolchain.cmake" \
    -DANDROID_ABI=arm64-v8a \
    -DANDROID_PLATFORM=android-29 \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_C_FLAGS="-march=armv8.7a" \
    -DCMAKE_CXX_FLAGS="-march=armv8.7a $HPP_FLAG" \
    -DCMAKE_SHARED_LINKER_FLAGS="-Wl,-z,max-page-size=16384" \
    -DCMAKE_EXE_LINKER_FLAGS="-Wl,-z,max-page-size=16384" \
    -DGGML_OPENMP=OFF \
    -DGGML_LLAMAFILE=OFF \
    -DGGML_NATIVE=OFF \
    -DGGML_VULKAN="$vulkan" \
    -DLLAMA_CURL=OFF \
    -DLLAMA_BUILD_TESTS=OFF \
    -DLLAMA_BUILD_EXAMPLES=ON \
    -DLLAMA_BUILD_SERVER=OFF
  cmake --build "$dir" --target llama-cli llama-embedding -j"${JOBS:-4}"
}
if ! build_one ON; then
  echo "Vulkan 没编过,改用 CPU。Adreno 后端这次没有放进 APK。" >&2
  build_one OFF
  echo "cpu" > "$SRC/build-android/BACKEND.txt"
else
  echo "vulkan" > "$SRC/build-android/BACKEND.txt"
fi
BIN=$SRC/build-android/bin
mkdir -p "$DEST"
cp "$BIN/libllama.so" "$DEST/libllama.so"
cp "$BIN/libggml.so" "$DEST/libggml.so"
cp "$BIN/libggml-base.so" "$DEST/libggml-base.so"
cp "$BIN/libggml-cpu.so" "$DEST/libggml-cpu.so"
if [ -f "$BIN/libggml-vulkan.so" ]; then
  cp "$BIN/libggml-vulkan.so" "$DEST/libggml-vulkan.so"
else
  rm -f "$DEST/libggml-vulkan.so"
fi
cp "$BIN/llama-cli" "$DEST/libllama-cli.so"
cp "$BIN/llama-embedding" "$DEST/libllama-embedding.so"
rm -f "$DEST/libllama-finetune-lora.so"
if [ -n "$STRIP" ]; then
  for f in "$DEST"/libllama.so "$DEST"/libggml.so "$DEST"/libggml-base.so "$DEST"/libggml-cpu.so "$DEST"/libggml-vulkan.so "$DEST"/libllama-cli.so "$DEST"/libllama-embedding.so; do
    [ -f "$f" ] || continue
    "$STRIP" "$f" || true
  done
fi
chmod 755 "$DEST"/libllama-cli.so "$DEST"/libllama-embedding.so
echo "后端 $(cat "$SRC/build-android/BACKEND.txt")"
ls -lh "$DEST"/libllama.so "$DEST"/libggml*.so "$DEST"/libllama-cli.so "$DEST"/libllama-embedding.so

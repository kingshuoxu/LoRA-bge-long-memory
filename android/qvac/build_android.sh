#!/bin/sh
# 用和桌面同一份 QVAC 源码编 Android arm64 的 libllama。
# 仓库 tetherto/qvac-fabric-llm.cpp,提交 b73e75af5,再打上 bert-bge-cased 补丁,这样大写词不会被 WPM 折成小写。
# Vulkan 和带 dotprod/i8mm 的 ggml-cpu 一起打进 APK。
# 小米 15 的 Adreno 走原来的 Vulkan 路径。ARM Mali / Immortalis(厂商 0x13B5)在运行时关掉
# coopmat 和 bf16,保留 fp16,并按真实子组宽度排 tile。应用仍会拿 GPU 和 CPU 对一下。
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")"/../.. && pwd)
COMMIT=b73e75af5f2ab69c0e8984637c743c6a50ebc98d
PATCH=$ROOT/android/qvac/wpm-cased.patch
MALI_PATCH=$ROOT/android/qvac/mali-vulkan.patch
SHADER_PATCH=$ROOT/android/qvac/shader-generation.patch
MALI_HEADER=$ROOT/android/qvac/mali_vulkan_policy.h
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
# 主机上先编 Mali 策略测试。没有 Mali 硬件时,CI 靠这份测试锁住 0x13B5 的分支。
c++ -std=c++17 -Wall -Werror -o /tmp/test_mali_policy "$ROOT/android/qvac/test_mali_policy.cpp"
/tmp/test_mali_policy
# 桌面用的是 tetherto/qvac-fabric-llm.cpp 的 b73e75af5。公开的 finetune 镜像里没有这个提交。
REPO=https://github.com/tetherto/qvac-fabric-llm.cpp.git
if [ ! -e "$SRC/.git" ]; then
  git init "$SRC"
  git -C "$SRC" remote add origin "$REPO"
fi
git -C "$SRC" fetch --depth 1 origin "$COMMIT"
git -C "$SRC" checkout --force --detach FETCH_HEAD
git -C "$SRC" clean -fd -e build-android
git -C "$SRC" apply --check "$PATCH"
git -C "$SRC" apply "$PATCH"
git -C "$SRC" apply --check "$MALI_PATCH"
git -C "$SRC" apply "$MALI_PATCH"
git -C "$SRC" apply --check "$SHADER_PATCH"
git -C "$SRC" apply "$SHADER_PATCH"
python3 "$ROOT/android/qvac/test_shader_generation.py" "$SRC/ggml/src/ggml-vulkan/vulkan-shaders/vulkan-shaders-gen.cpp"
cp "$MALI_HEADER" "$SRC/ggml/src/ggml-vulkan/mali_vulkan_policy.h"
if ! command -v glslc >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update -qq && apt-get install -y -qq glslc || true
  fi
fi
# NDK 27.2 ships Vulkan C headers 1.3.275. Never mix them with the runner's
# rolling libvulkan-dev Hpp (Ubuntu 26.04 currently ships header version 341).
# Official KhronosGroup/Vulkan-Hpp v1.3.275, pinned by immutable commit:
# https://github.com/KhronosGroup/Vulkan-Hpp/tree/1a24b015830c116632a0723f3ccfd1f06009ce12
VULKAN_HEADER_VERSION=275
VULKAN_HPP_COMMIT=1a24b015830c116632a0723f3ccfd1f06009ce12
CORE=$(find "$NDK/toolchains/llvm/prebuilt" -path '*/sysroot/usr/include/vulkan/vulkan_core.h' | head -1)
test -n "$CORE"
NDK_HEADER_VERSION=$(awk '$1 == "#define" && $2 == "VK_HEADER_VERSION" { print $3; exit }' "$CORE")
if [ "$NDK_HEADER_VERSION" != "$VULKAN_HEADER_VERSION" ]; then
  echo "Expected NDK Vulkan header $VULKAN_HEADER_VERSION, found $NDK_HEADER_VERSION. Update the NDK and Vulkan-Hpp pins together." >&2
  exit 1
fi
HPP="$ROOT/android/out/build-deps/vulkan-hpp-$VULKAN_HPP_COMMIT"
if [ ! -d "$HPP/.git" ]; then
  git init "$HPP"
  git -C "$HPP" remote add origin https://github.com/KhronosGroup/Vulkan-Hpp.git
fi
git -C "$HPP" fetch --depth 1 origin "$VULKAN_HPP_COMMIT"
git -C "$HPP" checkout --force --detach "$VULKAN_HPP_COMMIT"
test "$(git -C "$HPP" rev-parse HEAD)" = "$VULKAN_HPP_COMMIT"
# Hpp contains only C++ wrappers. idirafter leaves the NDK's C headers first.
HPP_FLAG="-idirafter $HPP"
NDK_PREBUILT=${CORE%/sysroot/usr/include/vulkan/vulkan_core.h}
printf '#include <vulkan/vulkan.hpp>\nstatic_assert(VK_HEADER_VERSION == 275, "Unexpected Vulkan headers");\n' |
  "$NDK_PREBUILT/bin/aarch64-linux-android29-clang++" -std=c++17 -idirafter "$HPP" -x c++ -fsyntax-only -
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
    -DCMAKE_C_FLAGS="-march=armv8.7-a" \
    -DCMAKE_CXX_FLAGS="-march=armv8.7-a $HPP_FLAG" \
    -DCMAKE_SHARED_LINKER_FLAGS="-Wl,-z,max-page-size=16384" \
    -DCMAKE_EXE_LINKER_FLAGS="-Wl,-z,max-page-size=16384" \
    -DGGML_OPENMP=OFF \
    -DGGML_LLAMAFILE=OFF \
    -DGGML_NATIVE=OFF \
    -DGGML_CPU_ARM_ARCH=armv8.7-a+dotprod+i8mm \
    -DGGML_VULKAN="$vulkan" \
    -DLLAMA_CURL=OFF \
    -DLLAMA_BUILD_TESTS=OFF \
    -DLLAMA_BUILD_EXAMPLES=ON \
    -DLLAMA_BUILD_SERVER=OFF
  cmake --build "$dir" --target llama-cli llama-embedding -j"${JOBS:-4}"
}
build_one ON
echo "vulkan+cpu" > "$SRC/build-android/BACKEND.txt"
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
test -f "$DEST/libggml-cpu.so"
test -f "$DEST/libggml-vulkan.so"
OBJDUMP=$(find "$NDK/toolchains/llvm/prebuilt" -name llvm-objdump | head -1)
test -n "$OBJDUMP"
"$OBJDUMP" -d "$DEST/libggml-cpu.so" | grep -m1 -E 'sdot|usdot' >/dev/null
"$OBJDUMP" -d "$DEST/libggml-cpu.so" | grep -m1 smmla >/dev/null
grep -a -q "ggml_vulkan: caps" "$DEST/libggml-vulkan.so"
echo "libggml-cpu.so 含 sdot 和 smmla"
echo "libggml-vulkan.so 含 Mali 能力日志"
echo "后端 $(cat "$SRC/build-android/BACKEND.txt")"
ls -lh "$DEST"/libllama.so "$DEST"/libggml*.so "$DEST"/libllama-cli.so "$DEST"/libllama-embedding.so

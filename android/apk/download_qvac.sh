#!/bin/sh
# 下载小米 15 / Adreno 830 用的 QVAC arm64 命令行,放进 APK 的 jniLibs。
# 这些文件名以 lib 开头,Android 才会把它们解压到 nativeLibraryDir,应用再直接 exec。
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
DEST=$ROOT/app/src/main/jniLibs/arm64-v8a
URL=${QVAC_URL:-https://media.githubusercontent.com/media/tether-ai-research/qvac-fabric-llm-finetune/main/releases/android/qvac-android-adreno-arm64-v1.0.zip}
SHA=3a09dad897f97b85c87374c7b40d1c51377a900c5a3f88e60c9d4059fc758b32
ZIP=${QVAC_ZIP:-/tmp/qvac-android-adreno-arm64-v1.0.zip}
if [ ! -f "$ZIP" ]; then
  wget -O "$ZIP" "$URL"
fi
echo "$SHA  $ZIP" | sha256sum -c -
rm -rf /tmp/qvac-adreno-unpack
mkdir -p /tmp/qvac-adreno-unpack "$DEST"
unzip -q -o "$ZIP" -d /tmp/qvac-adreno-unpack
BIN=$(find /tmp/qvac-adreno-unpack -type d -name bin | head -1)
cp "$BIN/libggml-base.so" "$BIN/libggml-cpu.so" "$BIN/libggml-vulkan.so" "$BIN/libggml.so" "$BIN/libllama.so" "$DEST/"
cp "$BIN/llama-cli" "$DEST/libllama-cli.so"
cp "$BIN/llama-embedding" "$DEST/libllama-embedding.so"
cp "$BIN/llama-finetune-lora" "$DEST/libllama-finetune-lora.so"
chmod 755 "$DEST"/libllama-cli.so "$DEST"/libllama-embedding.so "$DEST"/libllama-finetune-lora.so
echo "已放入 $DEST"
ls -lh "$DEST"

#!/bin/sh
# 下载官方 Qwen2.5-0.5B-Instruct Q8_0。桌面训练探针和手机上的 train_base.gguf 用这份。
# 对话要 50/50 时用 convert_base.sh 产出的 f16,Q8_0 在产品编号上会错 5 条。
# 文件来自 https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF (general.architecture = qwen2)。
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
OUT=${OUT:-$ROOT/models/qwen2.5-0.5b-instruct-q8_0.gguf}
URL=${URL:-https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q8_0.gguf}
mkdir -p "$(dirname "$OUT")"
if [ -f "$OUT" ]; then
  echo "已有 $OUT"
else
  wget -c -O "$OUT" "$URL"
fi
# 2026-10-22 下载到的官方文件。大小变了就停下来核对,不要默默换一份。
EXPECT=675710816
SIZE=$(wc -c < "$OUT")
if [ "$SIZE" != "$EXPECT" ]; then
  echo "大小是 $SIZE 字节,预期 $EXPECT。若官方更新了文件,改 EXPECT 并重新做专家对照。" >&2
  exit 1
fi
echo "Q8_0 基座就绪: $OUT"

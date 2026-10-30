#!/bin/sh
# 在桌面用 QVAC llama-finetune-lora 训练一批。Qwen2 架构可以跑。
# 仓库的 lr 5e-4 和探针里的 1e-4 都会把全词表 loss 打高,这里默认 2e-5。
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
BATCH=${BATCH:-0}
LR=${LR:-2e-5}
EPOCHS=${EPOCHS:-12}
BIN=${QVAC_BIN:-$ROOT/android/out/qvac-b7349/build/bin/llama-finetune-lora}
BASE=${BASE:-$ROOT/models/qwen2.5-0.5b-instruct-q8_0.gguf}
PY=${PYTHON:-$ROOT/.venv/bin/python}
OUT=$ROOT/android/out/train_b$BATCH
mkdir -p "$OUT/checkpoints"
"$PY" "$ROOT/android/scripts/prepare_train_jsonl.py" --batch "$BATCH" --out "$OUT/batch_${BATCH}_sft.jsonl"
"$BIN" -m "$BASE" -f "$OUT/batch_${BATCH}_sft.jsonl" \
  --assistant-loss-only \
  --chat-template "$ROOT/android/templates/qwen25_chat_template.jinja" \
  --lora-rank 32 --lora-alpha 64 \
  --lora-modules ffn_gate,ffn_up,ffn_down \
  --learning-rate "$LR" --weight-decay 0 \
  --num-epochs "$EPOCHS" \
  -c 96 -b 96 -ngl 0 -fa off -t 4 --no-warmup \
  --checkpoint-save-steps 450 \
  --checkpoint-save-dir "$OUT/checkpoints" \
  --output-adapter "$OUT/expert_${BATCH}.gguf" \
  ${RESUME:+--resume-from "$RESUME"}
echo "适配器: $OUT/expert_${BATCH}.gguf"

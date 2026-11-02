#!/bin/sh
# 桌面用和手机同一份 C++ 训练 batch_0。
# 先 python3 android/scripts/prepare_mft_jsonl.py --out ... --eval-out ...
# 二进制默认是本机编好的 MobileFineTuner train_wikitext。
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")"/../.. && pwd)
BIN=${MFT_BIN:-/tmp/MobileFineTuner/examples/qwen_lora_finetune/build/train_wikitext}
MODEL=${MFT_MODEL:-$ROOT/models/Qwen2.5-0.5B-Instruct}
JSONL=${1:?需要预分词 train.jsonl}
OUT=${2:?需要输出目录}
export OPENBLAS_NUM_THREADS=${OPENBLAS_NUM_THREADS:-4}
export OMP_NUM_THREADS=${OMP_NUM_THREADS:-4}
exec "$BIN" \
  --model_dir "$MODEL" \
  --jsonl_train "$JSONL" \
  --output_dir "$OUT" \
  --output_gguf "$OUT/adapter.gguf" \
  --seq_len "${SEQ_LEN:-40}" \
  --batch_size "${BATCH:-8}" \
  --epochs "${EPOCHS:-4}" \
  --lr "${LR:-5e-4}" \
  --max_grad_norm 1.0 \
  --lora_r 32 --lora_alpha 64 --lora_dropout 0 \
  --mlp --base_weight_storage fp32 --seed 42 \
  --save_every "${SAVE_EVERY:-57}"

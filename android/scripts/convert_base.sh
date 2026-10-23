#!/bin/sh
# 把本地 Hugging Face 的 Qwen2.5-0.5B-Instruct 转成 f16 GGUF。
# 官方 Q8_0 挂 expert_0 是 45/50,同一份 LoRA 在这份 f16 上是 50/50。
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
LLAMA_CPP=${LLAMA_CPP:-/tmp/llama.cpp-b7349}
MODEL=${MODEL:-$ROOT/models/Qwen2.5-0.5B-Instruct}
OUT=${OUT:-$ROOT/android/out/gguf/qwen2.5-0.5b-instruct-f16.gguf}
if [ -n "${PYTHON:-}" ]; then
  PY=$PYTHON
elif [ -x "$ROOT/.venv/bin/python" ]; then
  PY=$ROOT/.venv/bin/python
else
  PY=python3
fi
if [ ! -f "$LLAMA_CPP/convert_hf_to_gguf.py" ]; then
  git clone --depth 1 --branch b7349 https://github.com/ggml-org/llama.cpp.git "$LLAMA_CPP"
fi
mkdir -p "$(dirname "$OUT")"
PYTHONPATH="$LLAMA_CPP/gguf-py${PYTHONPATH:+:$PYTHONPATH}" \
  "$PY" "$LLAMA_CPP/convert_hf_to_gguf.py" "$MODEL" --outtype f16 --outfile "$OUT"
echo "写出 $OUT"
echo "记忆对照用这份 f16。手机存储紧时可以用官方 Q8_0,旗舰型号会错 5/50。"

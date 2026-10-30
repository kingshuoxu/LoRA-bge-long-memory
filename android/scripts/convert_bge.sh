#!/bin/sh
# 把 bge-small-zh-v1.5 转成 f16 GGUF。推理时必须 --pooling mean --embd-normalize 2。
# bge 只有约 24M 参数,不量化,避免均值池化的余弦掉到 0.999 以下。
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
LLAMA_CPP=${LLAMA_CPP:-/tmp/llama.cpp-b7349}
MODEL=${MODEL:-$ROOT/models/bge-small-zh-v1.5}
OUT=${OUT:-$ROOT/android/out/gguf/bge-small-zh-v1.5-f16.gguf}
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
# b7349 认得 bge-small-en 和 bge-large-zh,不认得 bge-small-zh-v1.5 的分词器指纹。
# 这个模型是 Bert WordPiece,和英文 bge 走同一套 WPM,补上指纹即可。
HASH=56a3532a4cda32cf10d09834e0cdeee45c407d750b868651e44e2eebdcc721ed
# 写成 bert-bge-cased:运行时不把拉丁字母转成小写,和 BertTokenizer(do_lower_case=false) 一致。
"$PY" - "$LLAMA_CPP/convert_hf_to_gguf.py" "$HASH" <<'PY'
import sys
from pathlib import Path
path, digest = sys.argv[1], sys.argv[2]
file = Path(path)
text = file.read_text()
block = (
    f'        if chkhsh == "{digest}":\n'
    '            # ref: https://huggingface.co/BAAI/bge-small-zh-v1.5\n'
    '            res = "bert-bge-cased"\n'
)
old = block.replace('res = "bert-bge-cased"', 'res = "bert-bge"')
if block in text:
    pass
elif old in text:
    text = text.replace(old, block, 1)
else:
    anchor = '            # ref: https://huggingface.co/BAAI/bge-small-en-v1.5\n            res = "bert-bge"\n'
    if anchor not in text:
        raise SystemExit("convert_hf_to_gguf.py 里没有 bge-small-en 锚点,不能补指纹")
    text = text.replace(anchor, anchor + block, 1)
file.write_text(text)
PY
# 空的 sentencepiece 文件会让转换器走错分词器。这个模型用的是 WordPiece。
if [ -f "$MODEL/sentencepiece.bpe.model" ] && [ ! -s "$MODEL/sentencepiece.bpe.model" ]; then
  rm -f "$MODEL/sentencepiece.bpe.model"
fi
mkdir -p "$(dirname "$OUT")"
PYTHONPATH="$LLAMA_CPP/gguf-py${PYTHONPATH:+:$PYTHONPATH}" \
  "$PY" "$LLAMA_CPP/convert_hf_to_gguf.py" "$MODEL" --outtype f16 --outfile "$OUT"
echo "写出 $OUT"
echo "手机上编码问句: llama-embedding -m $OUT --pooling mean --embd-normalize 2 --embd-output-format raw -p '问句'"

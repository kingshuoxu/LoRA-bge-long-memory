#!/bin/sh
# 下载 Qwen 和 bge,转成手机用的 f16,导出五个专家,并写出带 SHA256 的清单。
# 镜像顺序: ModelScope、hf-mirror.com、huggingface.co,最后是 GitHub Release。
# 只有和我们自己转换出来的字节完全相同的官方 f16,才会放在基座的前面。
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
cd "$ROOT"
QWEN=$ROOT/models/Qwen2.5-0.5B-Instruct
BGE=$ROOT/models/bge-small-zh-v1.5
GGUF=$ROOT/android/out/gguf
BUNDLE=$ROOT/android/out/phone-bundle
STAGE=$ROOT/android/out/release
TAG=${RELEASE_TAG:-android-v0.1.0}
REPO=${GITHUB_REPOSITORY:-kingshuoxu/LoRA-bge-long-memory}
BASE_GGUF=$GGUF/qwen2.5-0.5b-instruct-f16.gguf
BGE_GGUF=$GGUF/bge-small-zh-v1.5-f16.gguf
RELEASE_BASE=https://github.com/$REPO/releases/download/$TAG

fetch() {
  dest=$1
  shift
  if [ -f "$dest" ]; then
    echo "已有 $dest"
    return
  fi
  mkdir -p "$(dirname "$dest")"
  for url in "$@"; do
    echo "取 $url"
    if curl -fL --retry 3 --retry-delay 2 -o "$dest.partial" "$url"; then
      mv "$dest.partial" "$dest"
      return
    fi
    rm -f "$dest.partial"
    echo "失败,换下一个镜像" >&2
  done
  echo "下载失败: $dest" >&2
  exit 1
}

ms() { printf 'https://modelscope.cn/models/%s/resolve/master/%s' "$1" "$2"; }
hf() { printf 'https://huggingface.co/%s/resolve/main/%s' "$1" "$2"; }
hm() { printf 'https://hf-mirror.com/%s/resolve/main/%s' "$1" "$2"; }

qwen_files="config.json generation_config.json merges.txt tokenizer.json tokenizer_config.json vocab.json model.safetensors"
for name in $qwen_files; do
  fetch "$QWEN/$name" "$(ms Qwen/Qwen2.5-0.5B-Instruct "$name")" "$(hm Qwen/Qwen2.5-0.5B-Instruct "$name")" "$(hf Qwen/Qwen2.5-0.5B-Instruct "$name")"
done
bge_files="config.json tokenizer.json tokenizer_config.json vocab.txt special_tokens_map.json model.safetensors"
for name in $bge_files; do
  fetch "$BGE/$name" "$(ms BAAI/bge-small-zh-v1.5 "$name")" "$(hm BAAI/bge-small-zh-v1.5 "$name")" "$(hf BAAI/bge-small-zh-v1.5 "$name")"
done

python3 - << 'PY'
from pathlib import Path
pointer = Path("experts/expert_0/adapter_model.safetensors").read_bytes()[:20]
if pointer.startswith(b"version https://git-lfs"):
    raise SystemExit("专家权重还是 Git LFS 指针。先 git lfs pull --include 'experts/**'")
qwen = Path("models/Qwen2.5-0.5B-Instruct/model.safetensors").stat().st_size
bge = Path("models/bge-small-zh-v1.5/model.safetensors").stat().st_size
if qwen < 100_000_000 or bge < 10_000_000:
    raise SystemExit(f"权重不完整: qwen {qwen} bge {bge}")
PY
# Qwen2 先尝试 sentencepiece,没有 tokenizer.model 再退回 vocab.json。
# 没装这个包时,缺模块的异常盖住了「文件不存在」,转换会直接停。
if ! python3 -c "import sentencepiece" >/dev/null 2>&1; then
  pip install sentencepiece
fi
sh android/scripts/convert_base.sh
sh android/scripts/convert_bge.sh
python android/scripts/convert_experts.py
python android/scripts/export_phone_bundle.py

BASE_URLS="$RELEASE_BASE/qwen2.5-0.5b-instruct-f16.gguf"
OFFICIAL_MS=$(ms Qwen/Qwen2.5-0.5B-Instruct-GGUF qwen2.5-0.5b-instruct-fp16.gguf)
OFFICIAL_HM=$(hm Qwen/Qwen2.5-0.5B-Instruct-GGUF qwen2.5-0.5b-instruct-fp16.gguf)
OFFICIAL_HF=$(hf Qwen/Qwen2.5-0.5B-Instruct-GGUF qwen2.5-0.5b-instruct-fp16.gguf)
if curl -fL --retry 2 --retry-delay 2 -o "$GGUF/official-fp16.gguf" "$OFFICIAL_MS"; then
  if cmp -s "$BASE_GGUF" "$GGUF/official-fp16.gguf"; then
    echo "官方 f16 和本地转换字节相同,基座先走 ModelScope。"
    BASE_URLS="$OFFICIAL_MS $OFFICIAL_HM $OFFICIAL_HF $BASE_URLS"
  else
    echo "官方 f16 和本地转换不同,基座只用这次发布的文件。"
  fi
  rm -f "$GGUF/official-fp16.gguf"
else
  echo "没有拿到官方 f16,基座只用这次发布的文件。"
fi

mkdir -p "$STAGE"
cp "$BASE_GGUF" "$STAGE/qwen2.5-0.5b-instruct-f16.gguf"
cp "$BGE_GGUF" "$STAGE/bge-small-zh-v1.5-f16.gguf"
export ROOT
export GITHUB_REPOSITORY="$REPO"
export RELEASE_TAG="$TAG"
python3 - /tmp/setup-plan.json "$BASE_URLS" << 'PY'
import json, os, shutil, sys
from pathlib import Path
plan_path, base_urls = sys.argv[1], sys.argv[2].split()
root = Path(os.environ["ROOT"])
stage = root / "android/out/release"
qwen = root / "models/Qwen2.5-0.5B-Instruct"
bundle = root / "android/out/phone-bundle"
repo = os.environ["GITHUB_REPOSITORY"]
tag = os.environ["RELEASE_TAG"]
release = f"https://github.com/{repo}/releases/download/{tag}"

def mirrors(repo_id, name, release_name):
    return [
        f"https://modelscope.cn/models/{repo_id}/resolve/master/{name}",
        f"https://hf-mirror.com/{repo_id}/resolve/main/{name}",
        f"https://huggingface.co/{repo_id}/resolve/main/{name}",
        f"{release}/{release_name}",
    ]

rows = [{
    "id": "base-gguf",
    "dest": "models/base.gguf",
    "src": str(root / "android/out/gguf/qwen2.5-0.5b-instruct-f16.gguf"),
    "urls": base_urls,
}]
rows.append({
    "id": "bge-gguf",
    "dest": "models/bge.gguf",
    "src": str(root / "android/out/gguf/bge-small-zh-v1.5-f16.gguf"),
    "urls": [f"{release}/bge-small-zh-v1.5-f16.gguf"],
})
for name in ["config.json", "generation_config.json", "merges.txt", "tokenizer.json", "tokenizer_config.json", "vocab.json", "model.safetensors"]:
    release_name = "qwen-" + name.replace("/", "-")
    shutil.copyfile(qwen / name, stage / release_name)
    rows.append({
        "id": "qwen-" + name,
        "dest": f"models/Qwen2.5-0.5B-Instruct/{name}",
        "src": str(qwen / name),
        "urls": mirrors("Qwen/Qwen2.5-0.5B-Instruct", name, release_name),
    })
for path in sorted(bundle.rglob("*")):
    if not path.is_file():
        continue
    rel = path.relative_to(bundle).as_posix()
    release_name = "bundle-" + rel.replace("/", "-")
    shutil.copyfile(path, stage / release_name)
    rows.append({
        "id": "bundle-" + rel,
        "dest": f"import/{rel}",
        "src": str(path),
        "urls": [f"{release}/{release_name}"],
    })
Path(plan_path).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"计划 {len(rows)} 个文件")
PY
python3 android/scripts/write_setup_manifest.py /tmp/setup-plan.json "$STAGE/manifest.json"
cp "$STAGE/manifest.json" android/apk/app/src/main/assets/setup_manifest.json
echo "清单已写入 assets,发布文件在 $STAGE"
# 后面还要编 OpenBLAS 和 Vulkan。源权重、中间 GGUF 和 llama.cpp 树不再需要。
if [ -n "${GITHUB_ACTIONS:-}" ]; then
  rm -rf "$QWEN" "$BGE" "$GGUF" "$BUNDLE" "${LLAMA_CPP:-/tmp/llama.cpp-b7349}"
fi

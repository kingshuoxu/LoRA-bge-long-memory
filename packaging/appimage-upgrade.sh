#!/usr/bin/env bash
# 用 0.1.9 的 AppImage 拉 0.2.0，确认对话、专家和模型标记还在。
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

node desktop/update-plan.test.js

version="$(node -p "require('./desktop/package.json').version")"
prev="0.1.9"
if [ "$version" = "$prev" ]; then
  echo "当前版本不能等于 $prev" >&2
  exit 1
fi

new_app="$root/desktop/dist/LoRA-bge-memory-${version}-linux-x86_64.AppImage"
yml="$root/desktop/dist/latest-linux.yml"
if [ ! -f "$new_app" ] || [ ! -f "$yml" ]; then
  echo "缺少 $new_app 或 latest-linux.yml" >&2
  exit 1
fi

python3 - "$yml" "$version" <<'PY'
import pathlib, sys
text = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
version = sys.argv[2]
if f"version: {version}" not in text and f"version: '{version}'" not in text:
    sys.exit("latest-linux.yml 里没有当前版本")
if "AppImage" not in text:
    sys.exit("latest-linux.yml 里没有 AppImage")
if "blockMapSize" not in text and not list(pathlib.Path(sys.argv[1]).parent.glob("*.blockmap")):
    sys.exit("没有 blockmap，差分下载不会生效")
print("UPDATE_YML_OK")
PY

export CSC_IDENTITY_AUTO_DISCOVERY=false
rm -rf "$root/desktop/dist-prev"
(
  cd "$root/desktop"
  npx electron-builder --publish never --linux AppImage \
    -c.extraMetadata.version="$prev" \
    -c.directories.output=dist-prev
)

old_app="$root/desktop/dist-prev/LoRA-bge-memory-${prev}-linux-x86_64.AppImage"
if [ ! -f "$old_app" ]; then
  echo "没有打出 $old_app" >&2
  exit 1
fi

feed="$(mktemp -d)"
cp "$new_app" "$yml" "$feed/"
for blockmap in "$root"/desktop/dist/*.blockmap; do
  if [ -f "$blockmap" ]; then
    cp "$blockmap" "$feed/"
  fi
done

port="${UPGRADE_PORT:-8765}"
python3 -m http.server "$port" --bind 127.0.0.1 --directory "$feed" >/tmp/lora-upgrade-feed.log 2>&1 &
server_pid=$!
cleanup() {
  if [ -n "${server_pid:-}" ]; then
    kill "$server_pid" >/dev/null 2>&1 || true
    wait "$server_pid" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

work="$(mktemp -d)"
export HOME="$work/home"
export XDG_CONFIG_HOME="$work/config"
export XDG_DATA_HOME="$work/data"
export XDG_CACHE_HOME="$work/cache"
data="$XDG_CONFIG_HOME/lora-bge-memory"
mkdir -p "$data/experts/demo" "$data/models" "$HOME"
printf 'UPGRADE_KEEP' > "$data/conversations.sqlite"
printf 'keep' > "$data/experts/demo/keep.txt"
printf 'keep' > "$data/models/sentinel.txt"
printf '%s\n' '{"locale":"zh-CN","update_url":"http://127.0.0.1:'"$port"'/"}' > "$data/settings.json"

cache="${LORA_MEMORY_MODELS:-$root/model-cache}"
qwen="$cache/Qwen2.5-0.5B-Instruct/model.safetensors"
bge="$cache/bge-small-zh-v1.5/model.safetensors"
if [ -f "$qwen" ] && [ -f "$bge" ]; then
  qsize="$(stat -c%s "$qwen")"
  bsize="$(stat -c%s "$bge")"
  if [ "$qsize" -ge 500000000 ] && [ "$bsize" -ge 10000000 ]; then
    mkdir -p "$data/models/Qwen2.5-0.5B-Instruct" "$data/models/bge-small-zh-v1.5"
    ln "$qwen" "$data/models/Qwen2.5-0.5B-Instruct/model.safetensors" 2>/dev/null || cp -a "$qwen" "$data/models/Qwen2.5-0.5B-Instruct/model.safetensors"
    ln "$bge" "$data/models/bge-small-zh-v1.5/model.safetensors" 2>/dev/null || cp -a "$bge" "$data/models/bge-small-zh-v1.5/model.safetensors"
    echo "UPGRADE_MODELS_LINKED"
  fi
fi

run_dir="$work/run"
mkdir -p "$run_dir"
cp "$old_app" "$run_dir/LoRA-bge-memory.AppImage"
chmod +x "$run_dir/LoRA-bge-memory.AppImage"

export LORA_MEMORY_UPDATE_URL="http://127.0.0.1:${port}/"
export LORA_MEMORY_UPGRADE_STAMP=1
export APPIMAGE_EXTRACT_AND_RUN=1

set +e
timeout 240 xvfb-run -a "$run_dir/LoRA-bge-memory.AppImage" --appimage-extract-and-run --no-sandbox --disable-gpu --upgrade-smoke >"$run_dir/upgrade.log" 2>&1
status=$?
set -e
if [ "$status" -ne 0 ]; then
  cat "$run_dir/upgrade.log" >&2 || true
  if [ "$status" -eq 127 ] && grep -q "Failed to clean up cache directory" "$run_dir/upgrade.log"; then
    echo "APPIMAGE_CLEANUP_IGNORED"
  else
    echo "升级进程退出 $status" >&2
    exit "$status"
  fi
fi

stamp="$data/upgrade-stamp.json"
for _ in $(seq 1 30); do
  if [ -f "$stamp" ]; then
    break
  fi
  sleep 1
done

cmp "$run_dir/LoRA-bge-memory.AppImage" "$new_app"
python3 - "$data" "$version" <<'PY'
import json, pathlib, sys
data = pathlib.Path(sys.argv[1])
version = sys.argv[2]
marker = (data / "conversations.sqlite").read_bytes()
if b"UPGRADE_KEEP" not in marker:
    sys.exit("对话标记丢了")
if (data / "experts" / "demo" / "keep.txt").read_text(encoding="utf-8").strip() != "keep":
    sys.exit("专家标记丢了")
if (data / "models" / "sentinel.txt").read_text(encoding="utf-8").strip() != "keep":
    sys.exit("模型标记丢了")
settings = json.loads((data / "settings.json").read_text(encoding="utf-8"))
if settings.get("locale") != "zh-CN":
    sys.exit("设置丢了")
stamp = json.loads((data / "upgrade-stamp.json").read_text(encoding="utf-8"))
if stamp.get("version") != version:
    sys.exit(f"升级后的版本不是 {version}: {stamp}")
qwen = data / "models" / "Qwen2.5-0.5B-Instruct" / "model.safetensors"
if qwen.is_file() and qwen.stat().st_size >= 500_000_000 and not stamp.get("modelsReady"):
    sys.exit("模型还在，但升级后又去检查失败")
print("APPIMAGE_UPGRADE_OK", version)
PY

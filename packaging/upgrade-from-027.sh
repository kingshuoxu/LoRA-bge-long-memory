#!/usr/bin/env bash
# 用已发布的 0.2.7 AppImage 检查更新到当前安装包，确认用户目录还在。
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

version="$(node -p "require('./desktop/package.json').version")"
prev="0.2.7"
new_app="$root/desktop/dist/Yingyu-${version}-linux-x86_64.AppImage"
yml="$root/desktop/dist/latest-linux.yml"
if [ ! -f "$new_app" ] || [ ! -f "$yml" ]; then
  echo "缺少 $new_app 或 latest-linux.yml" >&2
  exit 1
fi

cache="${LORA_MEMORY_PREV_APPIMAGE:-$root/packaging/cache/LoRA-bge-memory-${prev}-linux-x86_64.AppImage}"
if [ ! -f "$cache" ]; then
  mkdir -p "$(dirname "$cache")"
  url="https://github.com/kingshuoxu/LoRA-bge-long-memory/releases/download/desktop-v${prev}/LoRA-bge-memory-${prev}-linux-x86_64.AppImage"
  ok=0
  for attempt in 1 2 3 4 5 6; do
    rm -f "$cache"
    if curl -L --fail --retry 2 --retry-all-errors --retry-delay 5 -o "$cache" "$url"; then
      ok=1
      break
    fi
    echo "0.2.7 安装包下载失败，隔开再试 ($attempt)" >&2
    sleep $((attempt * 30))
  done
  if [ "$ok" != 1 ] || [ ! -s "$cache" ]; then
    echo "下载不到 0.2.7 安装包" >&2
    exit 1
  fi
fi

feed="$(mktemp -d)"
cp "$new_app" "$yml" "$feed/"
for blockmap in "$root"/desktop/dist/*.blockmap; do
  if [ -f "$blockmap" ]; then
    cp "$blockmap" "$feed/"
  fi
done

port="${UPGRADE_PORT:-8766}"
python3 -m http.server "$port" --bind 127.0.0.1 --directory "$feed" >/tmp/yingyu-upgrade-027.log 2>&1 &
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
mkdir -p "$data/experts/expert_1000"
printf '%s\n' '{
  "expert": "expert_1000",
  "display_name": "用户/徐金朔",
  "entities": ["用户"],
  "self": false,
  "facts": [{
    "id": "f1",
    "entity": "用户",
    "attr": "名字",
    "value": "徐金朔",
    "statement": "用户叫徐金朔。",
    "qa": [{"q": "用户的名字是什么？", "a": "徐金朔"}]
  }]
}' > "$data/experts/expert_1000/fact_memory.json"

run_dir="$work/run"
mkdir -p "$run_dir"
cp "$cache" "$run_dir/LoRA-bge-memory.AppImage"
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
    echo "0.2.7 升级进程退出 $status" >&2
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
if b"UPGRADE_KEEP" not in (data / "conversations.sqlite").read_bytes():
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
print("UPGRADE_027_OK", version)
PY
PYTHONPATH="$root" python3 - "$data" <<'PY'
import json, pathlib, sys
from memory_core.identity import migrate_user_identity
from memory_core.self_query import self_reply

data = pathlib.Path(sys.argv[1])
changed = migrate_user_identity(data)
if changed < 1:
    sys.exit("没有把「用户」并进关于你")
memory = json.loads((data / "experts" / "expert_1000" / "fact_memory.json").read_text(encoding="utf-8"))
if memory.get("display_name") != "关于你" or not memory.get("self"):
    sys.exit(f"专家没有改成关于你: {memory.get('display_name')}")

class Expert:
    def __init__(self, facts):
        self.name = "expert_1000"
        self.display_name = "关于你"
        self.fact_memory = {"facts": facts, "self": True}

expert = Expert(memory["facts"])
for question in ("我是谁？", "我叫什么名字？", "我的名字是什么？"):
    answer, owner, used = self_reply(question, [expert])
    if "徐金朔" not in (answer or "") or owner is None or not used:
        sys.exit(f"{question} 没有带来源地答出徐金朔: {answer}")
print("UPGRADE_027_NAME_OK")
PY

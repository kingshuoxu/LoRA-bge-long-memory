#!/bin/sh
# 无界面验收。不需要显示器，也不需要 GPU。
# AppImage 解包后：bash squashfs-root/resources/e2e-check.sh
# deb 安装后：lora-bge-memory-e2e
set -eu
# /usr/bin/lora-bge-memory-e2e 是指向这份脚本的符号链接。$0 停在 /usr/bin，要先解开链接。
SELF=$0
if command -v readlink >/dev/null 2>&1; then
  RESOLVED=$(readlink -f "$0" 2>/dev/null || true)
  if [ -n "$RESOLVED" ]; then
    SELF=$RESOLVED
  fi
fi
ROOT=$(CDPATH= cd -- "$(dirname "$SELF")" && pwd)
export PYTHONPATH="$ROOT/app${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONUNBUFFERED=1
export HF_HUB_DISABLE_TELEMETRY=1
export LORA_MEMORY_UI="$ROOT/ui"
if [ "$(uname -s)" = "Linux" ]; then
  export LD_LIBRARY_PATH="$ROOT/runtime/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
if [ -x "$ROOT/runtime/bin/python3" ]; then
  PY="$ROOT/runtime/bin/python3"
elif [ -x "$ROOT/runtime/python.exe" ]; then
  PY="$ROOT/runtime/python.exe"
else
  echo "找不到内置 Python：$ROOT/runtime" >&2
  exit 1
fi
exec "$PY" -m memory_core.e2e_check "$@"

#!/bin/bash
set -euo pipefail
APP_DIR="/opt/LoRA-bge-memory"
TARGET="${APP_DIR}/resources/e2e-check.sh"
if [ -f "$TARGET" ]; then
  chmod +x "$TARGET"
  ln -sfn "$TARGET" /usr/bin/lora-bge-memory-e2e
fi
if [ -x "${APP_DIR}/lora-bge-memory" ]; then
  ln -sfn "${APP_DIR}/lora-bge-memory" /usr/bin/lora-bge-memory
fi
# Electron 的 chrome-sandbox 需要 setuid，否则普通用户双击可能起不来窗口。
if [ -f "${APP_DIR}/chrome-sandbox" ]; then
  chown root:root "${APP_DIR}/chrome-sandbox"
  chmod 4755 "${APP_DIR}/chrome-sandbox"
fi

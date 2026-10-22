#!/bin/bash
set -euo pipefail
TARGET="/opt/LoRA-bge-memory/resources/e2e-check.sh"
if [ -f "$TARGET" ]; then
  chmod +x "$TARGET"
  ln -sfn "$TARGET" /usr/bin/lora-bge-memory-e2e
fi

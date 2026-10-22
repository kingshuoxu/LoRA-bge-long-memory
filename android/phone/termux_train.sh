#!/bin/sh
# 不装 APK、只在 Termux 里训练时用。二进制来自同一份 Adreno zip,解压后:
#   export LD_LIBRARY_PATH=$PWD/build/bin
#   sh termux_train.sh /path/to/base.gguf /path/to/train.jsonl /path/to/out
# 聊天模板默认用仓库里的 android/templates/qwen25_chat_template.jinja。
# 断点续训: RESUME=/path/to/checkpoint.gguf sh termux_train.sh ...
set -eu
BIN_DIR=${BIN_DIR:-$PWD/build/bin}
BASE=$1
JSONL=$2
OUTDIR=$3
mkdir -p "$OUTDIR/checkpoints"
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
TEMPLATE=${TEMPLATE:-$OUTDIR/qwen25_chat_template.jinja}
if [ ! -f "$TEMPLATE" ] && [ -f "$SCRIPT_DIR/../templates/qwen25_chat_template.jinja" ]; then
  cp "$SCRIPT_DIR/../templates/qwen25_chat_template.jinja" "$OUTDIR/qwen25_chat_template.jinja"
  TEMPLATE=$OUTDIR/qwen25_chat_template.jinja
fi
if [ ! -f "$TEMPLATE" ]; then
  echo "缺少聊天模板。把 qwen25_chat_template.jinja 放到 $OUTDIR,或设置 TEMPLATE。" >&2
  exit 1
fi
export LD_LIBRARY_PATH=$BIN_DIR
"$BIN_DIR/llama-finetune-lora" -m "$BASE" -f "$JSONL" \
  --assistant-loss-only \
  --chat-template "$TEMPLATE" \
  --lora-rank 32 --lora-alpha 64 \
  --lora-modules ffn_gate,ffn_up,ffn_down \
  --learning-rate "${LR:-2e-5}" --weight-decay 0 \
  --num-epochs "${EPOCHS:-12}" \
  -c 96 -b 96 -ngl 99 -fa off --no-warmup \
  --checkpoint-save-steps 200 \
  --checkpoint-save-dir "$OUTDIR/checkpoints" \
  --output-adapter "$OUTDIR/adapter.gguf" \
  ${RESUME:+--resume-from "$RESUME"} \
  > "$OUTDIR/train.log" 2>&1 &
TRAIN=$!
(
  echo "ts rss_kb hwm_kb thermal battery"
  while kill -0 "$TRAIN" 2>/dev/null; do
    ts=$(date +%s)
    rss=$(awk '/VmRSS/{print $2}' /proc/"$TRAIN"/status 2>/dev/null || echo na)
    hwm=$(awk '/VmHWM/{print $2}' /proc/"$TRAIN"/status 2>/dev/null || echo na)
    therm=$(cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null | tr '\n' ',' || true)
    bat=$(cat /sys/class/power_supply/battery/capacity 2>/dev/null || echo na)
    echo "$ts $rss $hwm ${therm:-na} ${bat:-na}"
    sleep 10
  done
) > "$OUTDIR/telemetry.log" 2>&1 &
TELE=$!
set +e
wait "$TRAIN"
code=$?
set -e
kill "$TELE" 2>/dev/null || true
wait "$TELE" 2>/dev/null || true
echo "训练退出 $code"
echo "日志 $OUTDIR/train.log  遥测 $OUTDIR/telemetry.log  适配器 $OUTDIR/adapter.gguf"
exit "$code"

#!/bin/sh
# 不装 APK、只在 Termux 里训练时用。
#   sh termux_train.sh /path/to/Qwen2.5-0.5B-Instruct /path/to/facts.jsonl /path/to/out
# facts.jsonl 每行 {"statement":"...","qa":[{"q":"...","a":"..."}]}。
# 训练程序是 android/trainer/build_android.sh 编出的 train_wikitext,或 APK 里的 libtrain-mft.so。
set -eu
BIN=${BIN:-$PWD/train_wikitext}
MODEL=$1
FACTS=$2
OUTDIR=$3
mkdir -p "$OUTDIR"
"$BIN" \
  --model_dir "$MODEL" \
  --facts_jsonl "$FACTS" \
  --output_dir "$OUTDIR" \
  --output_gguf "$OUTDIR/adapter.gguf" \
  --epochs "${EPOCHS:-4}" \
  --batch_size "${BATCH:-1}" \
  --grad_accum_steps "${GRAD_ACCUM:-8}" \
  --lr "${LR:-5e-4}" \
  --max_grad_norm 1.0 \
  --lora_r 32 --lora_alpha 64 --lora_dropout 0 \
  --mlp --base_weight_storage fp32 --seed 42 \
  --save_every 20 \
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

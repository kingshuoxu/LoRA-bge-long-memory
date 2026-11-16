#!/usr/bin/env python3
"""把一批事实写成 QVAC llama-finetune-lora 的 messages JSONL。

仓库的 FactDataset 是「陈述句整句算 loss + 8 条 QA 只在答案上算 loss」。
QVAC 开了 --assistant-loss-only 之后,loss 只会落在 assistant 上,而且一次运行
只能是一种格式。这里把陈述句也包成一轮对话(用户说「请记下这句话。」,
助手复述陈述句),这样陈述句和 QA 可以放在同一次训练里。

另外 b7349 把最后 5% 的样本划成验证、没有 --val-split 开关。脚本在打乱后
把开头的若干条再接到末尾,让 float32 的 0.95 切分仍然盖住每一条原始样本。
"""
import argparse
import json
import random
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def rows_for_batch(path: Path) -> list[dict]:
    rows = []
    for line in path.open(encoding="utf-8"):
        if not line.strip():
            continue
        fact = json.loads(line)
        rows.append({"messages": [
            {"role": "system", "content": "你是助手。"},
            {"role": "user", "content": "请记下这句话。"},
            {"role": "assistant", "content": fact["statement"]},
        ]})
        for qa in fact["qa"]:
            rows.append({"messages": [
                {"role": "system", "content": "你是助手。"},
                {"role": "user", "content": qa["q"]},
                {"role": "assistant", "content": qa["a"]},
            ]})
    return rows


def tail_for_val_split(n: int) -> int:
    """最少要再补多少条,float32 的 floor(n * 0.95) 才不少于原来的 n。"""
    k = 0
    while int(np.float32(n + k) * np.float32(0.95)) < n:
        k += 1
    return k


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=0)
    ap.add_argument("--data", type=Path, default=ROOT / "data")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    rows = rows_for_batch(args.data / f"batch_{args.batch}.jsonl")
    random.Random(args.seed).shuffle(rows)
    k = tail_for_val_split(len(rows))
    packed = rows + rows[:k]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for row in packed:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    split = int(np.float32(len(packed)) * np.float32(0.95))
    print(f"原始 {len(rows)} 条,补 {k} 条到验证尾部,共 {len(packed)} 条,训练切分 {split}")
    print(f"写入 {args.out}")


if __name__ == "__main__":
    main()

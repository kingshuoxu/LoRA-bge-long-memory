#!/usr/bin/env python3
"""把一批事实写成 MobileFineTuner 的预分词 JSONL。

分词和 loss 掩码跟 scripts/train_expert.py 的 FactDataset 对齐:
陈述句整句监督,QA 只监督答案(含 <|im_end|>)。
训练行是 {"ids":[...],"mask":[...]}。评估行带上问句、标准答案和前缀 token。
"""
import argparse
import json
from pathlib import Path

from transformers import AutoTokenizer

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", type=Path, default=ROOT / "models" / "Qwen2.5-0.5B-Instruct")
    ap.add_argument("--batch", type=Path, default=None)
    ap.add_argument("--batch-id", type=int, default=0)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--eval-out", type=Path, required=True)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--system", default="你是助手。")
    args = ap.parse_args()
    batch = args.batch or (ROOT / "data" / f"batch_{args.batch_id}.jsonl")
    tok = AutoTokenizer.from_pretrained(args.model)
    facts = [json.loads(line) for line in batch.open(encoding="utf-8")]
    facts = [f for f in facts if f.get("qa") and not f.get("_common")][: args.n]
    rows = []
    longest = 0
    for fact in facts:
        ids = tok(fact["statement"], truncation=True, max_length=128)["input_ids"]
        rows.append({"ids": ids, "mask": [1] * len(ids)})
        longest = max(longest, len(ids))
        for qa in fact["qa"]:
            prompt = tok.apply_chat_template(
                [{"role": "system", "content": args.system},
                 {"role": "user", "content": qa["q"]}],
                tokenize=False, add_generation_prompt=True)
            p_ids = tok(prompt, add_special_tokens=False)["input_ids"]
            a_ids = tok(qa["a"] + "<|im_end|>\n", add_special_tokens=False)["input_ids"]
            rows.append({"ids": p_ids + a_ids, "mask": [0] * len(p_ids) + [1] * len(a_ids)})
            longest = max(longest, len(p_ids) + len(a_ids))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    with args.eval_out.open("w", encoding="utf-8") as f:
        for fact in facts:
            q, gold = fact["qa"][0]["q"], fact["qa"][0]["a"]
            prompt = tok.apply_chat_template(
                [{"role": "system", "content": args.system},
                 {"role": "user", "content": q + " 请简短回答。"}],
                tokenize=False, add_generation_prompt=True)
            ids = tok(prompt, add_special_tokens=False)["input_ids"]
            f.write(json.dumps({"id": fact["id"], "gold": gold, "q": q, "ids": ids}, ensure_ascii=False) + "\n")
            longest = max(longest, len(ids))
    print(f"train_rows={len(rows)} facts={len(facts)} max_len={longest}")


if __name__ == "__main__":
    main()

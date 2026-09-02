"""泛化失败诊断:列出指定批次+问法下答错的题目(问题/模型答案/gold)。

用法: python scripts/debug/para_fail.py --rocm --data data_para --qidx 0 --batch 0
"""
import argparse
import json
import sys
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).parent.parent))
from eval_memory import answer, pick_device  # noqa: E402
from router import embed  # noqa: E402

from peft import PeftModel  # noqa: E402
from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, required=True)
    ap.add_argument("--qidx", type=int, default=0)
    ap.add_argument("--tau", type=float, default=0.6)
    ap.add_argument("--experts", type=Path, default=Path("experts"))
    ap.add_argument("--data", type=Path, default=Path("data_para"))
    ap.add_argument("--model", default="models/Qwen2.5-0.5B-Instruct")
    ap.add_argument("--cpu", action="store_true")
    ap.add_argument("--rocm", action="store_true")
    args = ap.parse_args()

    device = pick_device(args)
    tok = AutoTokenizer.from_pretrained(args.model)
    base = AutoModelForCausalLM.from_pretrained(args.model, torch_dtype=torch.float16).to(device)
    router = [json.loads(l) for l in (args.experts / "router.jsonl").open(encoding="utf-8")]
    first = router[0]
    model = PeftModel.from_pretrained(base, args.experts / first["expert"], adapter_name=first["expert"])
    for e in router[1:]:
        model.load_adapter(args.experts / e["expert"], adapter_name=e["expert"])
    model.eval()
    keys = {e["expert"]: torch.load(e["key_path"], weights_only=True) for e in router}

    facts = [json.loads(l) for l in open(args.data / f"batch_{args.batch}.jsonl", encoding="utf-8")]
    facts = [f for f in facts if f.get("qa") and not f.get("_common")][:50]

    for f in facts:
        q, gold = f["qa"][args.qidx]["q"], f["qa"][args.qidx]["a"]
        qv = embed([q])[0]
        best, s = max(((n, (k @ qv).max().item()) for n, k in keys.items()), key=lambda kv: kv[1])
        if s >= args.tau:
            model.set_adapter(best)
            ans = answer(model, tok, device, q)
        else:
            with model.disable_adapter():
                ans = answer(model, tok, device, q)
        if gold.rstrip("年") not in ans:
            print(f"[{f['attr']}] sim={s:.3f} ({best})\n  Q: {q}\n  A: {ans[:60]}\n  gold: {gold}")


if __name__ == "__main__":
    main()

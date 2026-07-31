"""G2 对照组:不做专家隔离,同一个 LoRA 顺序吃掉 5 批经验,测旧批遗忘。

与专家路线公平对照:
- 同一个 LoRA(r=32,FFN),按 batch_0 → batch_4 顺序续训,每批 12 epochs
  (与专家路线每批的训练预算相同),lr 5e-4(避免续训中途发散干扰观测);
- 全部训完后,逐批测记忆准确率(adapter 常开,QA 子串匹配);
- 另测批次 0 在 adapter 关闭时的基底下限(基座没见过虚构事实,应≈0)。

预期:顺序续训发生灾难性遗忘,批次 0/1 准确率显著低于专家路线的 88%/98%。

用法: python scripts/g2_control.py --rocm [--epochs 12] [--lr 5e-4]
"""
import argparse
import json
import sys
import time
from pathlib import Path

import torch
from peft import LoraConfig, get_peft_model
from torch.utils.data import DataLoader
from transformers import AutoModelForCausalLM, AutoTokenizer

sys.path.insert(0, str(Path(__file__).parent))
from train_expert import FactDataset, collate, selective_loss, pick_device

MODEL = "models/Qwen2.5-0.5B-Instruct"


@torch.no_grad()
def answer(model, tok, device, question: str, max_new_tokens: int = 50) -> str:
    messages = [{"role": "system", "content": "你是助手。"},
                {"role": "user", "content": question + " 请简短回答。"}]
    text = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tok(text, return_tensors="pt").to(device)
    out = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False,
                         pad_token_id=tok.eos_token_id)
    return tok.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()


def train_one_batch(model, tok, device, facts, args):
    ds = FactDataset(facts, tok)
    dl = DataLoader(ds, batch_size=args.bsz, shuffle=True,
                    collate_fn=lambda r: collate(r, tok.eos_token_id))
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.0)
    model.train()
    for epoch in range(args.epochs):
        total = 0.0
        for input_ids, labels in dl:
            input_ids, labels = input_ids.to(device), labels.to(device)
            loss = selective_loss(model, input_ids, labels)
            opt.zero_grad()
            loss.backward()
            opt.step()
            total += loss.item()
        if epoch % 4 == 0 or epoch == args.epochs - 1:
            print(f"    epoch {epoch}: loss={total / len(dl):.4f}", flush=True)


def eval_batch(model, tok, device, facts, use_adapter: bool) -> tuple[int, int]:
    model.eval()
    hit = 0
    for f in facts:
        q, gold = f["qa"][0]["q"], f["qa"][0]["a"]
        if use_adapter:
            ans = answer(model, tok, device, q)
        else:
            with model.disable_adapter():
                ans = answer(model, tok, device, q)
        if gold.rstrip("年") in ans:
            hit += 1
    return hit, len(facts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=12, help="每批训练轮数(与专家路线预算相同)")
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--bsz", type=int, default=64)
    ap.add_argument("--rank", type=int, default=32)
    ap.add_argument("--cpu", action="store_true")
    ap.add_argument("--rocm", action="store_true")
    args = ap.parse_args()

    device = pick_device(args)
    tok = AutoTokenizer.from_pretrained(MODEL)
    base = AutoModelForCausalLM.from_pretrained(MODEL, torch_dtype=torch.float32).to(device)
    lcfg = LoraConfig(r=args.rank, lora_alpha=args.rank * 2, lora_dropout=0.0,
                      target_modules=["gate_proj", "up_proj", "down_proj"], task_type="CAUSAL_LM")
    model = get_peft_model(base, lcfg)

    batches = [[json.loads(l) for l in open(f"data/batch_{k}.jsonl", encoding="utf-8")]
               for k in range(5)]

    print(f"G2 顺序续训:单 LoRA r={args.rank},每批 {args.epochs} epochs, lr={args.lr}", flush=True)
    t0 = time.perf_counter()
    for k, facts in enumerate(batches):
        print(f"  写入批次 {k}({len(facts)} 条事实)...", flush=True)
        train_one_batch(model, tok, device, facts, args)
    print(f"续训完成,共 {time.perf_counter() - t0:.0f}s", flush=True)

    print("\n逐批记忆准确率(adapter 常开):", flush=True)
    for k, facts in enumerate(batches):
        hit, n = eval_batch(model, tok, device, facts, use_adapter=True)
        print(f"  批次 {k}: {hit}/{n} ({hit / n:.0%})", flush=True)

    hit, n = eval_batch(model, tok, device, batches[0], use_adapter=False)
    print(f"\n基底下限(批次 0,adapter 关闭): {hit}/{n} ({hit / n:.0%})", flush=True)


if __name__ == "__main__":
    main()

"""基座模型 sanity check:
1. G4 基线:无上下文直接问虚构问题,预期答错/胡编(证明知识不在先验里);
2. G3 式上界:把事实放进 prompt,验证模型本身能做 QA。

用法: python scripts/base_sanity.py [--model Qwen/Qwen2.5-1.5B-Instruct] [--n 5]
"""
import argparse
import json

import torch
import torch_directml
from transformers import AutoModelForCausalLM, AutoTokenizer


def ask(model, tok, device, prompt: str, max_new_tokens: int = 50) -> str:
    messages = [{"role": "user", "content": prompt}]
    text = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tok(text, return_tensors="pt").to(device)
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False,
                             pad_token_id=tok.eos_token_id)
    return tok.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="models/Qwen2.5-1.5B-Instruct")
    ap.add_argument("--n", type=int, default=5, help="抽几条虚构事实测试")
    args = ap.parse_args()

    device = torch_directml.device()
    tok = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForCausalLM.from_pretrained(
        args.model, torch_dtype=torch.float16).to(device)
    model.eval()

    facts = [json.loads(line) for line in open("data/batch_0.jsonl", encoding="utf-8")][:args.n]

    print("=== G4 基线:无上下文直接问(预期:答错)===")
    for f in facts:
        q, gold = f["qa"][0]["q"], f["qa"][0]["a"]
        ans = ask(model, tok, device, q + " 请简短回答。")
        print(f"  Q: {q}\n  期望: {gold} | 模型: {ans}\n")

    print("=== G3 式上界:事实放 prompt(预期:答对)===")
    correct = 0
    for f in facts:
        q, gold = f["qa"][0]["q"], f["qa"][0]["a"]
        prompt = f"已知事实:{f['statement']}\n根据上述事实回答:{q} 请简短回答。"
        ans = ask(model, tok, device, prompt)
        hit = gold.rstrip("年") in ans
        correct += hit
        print(f"  Q: {q}\n  期望: {gold} | 模型: {ans} | {'✓' if hit else '✗'}\n")
    print(f"上下文 QA 准确率: {correct}/{len(facts)}")


if __name__ == "__main__":
    main()

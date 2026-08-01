"""通用能力基准:挂载 LoRA 专家后,基座的通用能力退化了吗?

CMMLU 抽样(默认 10 科 × 30 题 = 300 题),三种条件:
1. base:   裸基座(不挂专家)—— 能力基线;
2. router: 挂载全部专家 + bge 路由(τ=0.5)—— 真实用法;理想结果:基准题与专家键
           不相似,路由不激活 → 准确率 = base,激活率 ≈0;
3. forced: 强制激活最相似专家 —— 最坏情况(模拟交叉误射),量化"误射时的代价上限"。

用法: python scripts/eval_general.py --rocm --experts experts --model models/Qwen2.5-0.5B-Instruct
"""
import argparse
import csv
import json
import random
import re
import sys
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

sys.path.insert(0, str(Path(__file__).parent))
from router import embed
from train_expert import pick_device

SUBJECTS = ["agronomy", "anatomy", "chinese_history", "college_medicine", "computer_science",
            "elementary_mathematics", "high_school_physics", "professional_law", "logical", "world_history"]


def load_questions(per_subject: int, seed: int = 42) -> list[dict]:
    qs = []
    rng = random.Random(seed)
    for s in SUBJECTS:
        with open(f"data_bench/test/{s}.csv", encoding="utf-8") as f:
            rows = [r for r in csv.DictReader(f) if r["Answer"] in "ABCD"]
        for r in rng.sample(rows, min(per_subject, len(rows))):
            qs.append({"subject": s, "q": r["Question"],
                       "choices": [r["A"], r["B"], r["C"], r["D"]], "answer": r["Answer"]})
    return qs


@torch.no_grad()
def answer_mcq(model, tok, device, item: dict) -> str:
    body = item["q"] + "\n" + "\n".join(
        f"{L}. {c}" for L, c in zip("ABCD", item["choices"]))
    messages = [{"role": "system", "content": "你是助手。"},
                {"role": "user", "content": body + "\n请直接回答选项字母(A/B/C/D),不要解释。"}]
    text = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tok(text, return_tensors="pt").to(device)
    out = model.generate(**inputs, max_new_tokens=10, do_sample=False,
                         pad_token_id=tok.eos_token_id)
    ans = tok.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
    m = re.search(r"[ABCD]", ans)
    return m.group(0) if m else "?"


def run_condition(name, items, answer_fn) -> float:
    hit = 0
    for i, it in enumerate(items):
        if answer_fn(it) == it["answer"]:
            hit += 1
        if (i + 1) % 100 == 0:
            print(f"    [{name}] {i + 1}/{len(items)} acc={hit / (i + 1):.1%}", flush=True)
    acc = hit / len(items)
    print(f"  [{name}] 准确率 {hit}/{len(items)} = {acc:.1%}", flush=True)
    return acc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-subject", type=int, default=30)
    ap.add_argument("--experts", type=Path, default=Path("experts"))
    ap.add_argument("--model", default="models/Qwen2.5-0.5B-Instruct")
    ap.add_argument("--tau", type=float, default=0.5)
    ap.add_argument("--cpu", action="store_true")
    ap.add_argument("--rocm", action="store_true")
    args = ap.parse_args()

    device = pick_device(args)
    tok = AutoTokenizer.from_pretrained(args.model)
    base = AutoModelForCausalLM.from_pretrained(args.model, torch_dtype=torch.float16).to(device)
    items = load_questions(args.per_subject)
    print(f"CMMLU {len(SUBJECTS)} 科 × {args.per_subject} 题 = {len(items)};模型 {args.model}", flush=True)

    # ---- 1. 裸基座 ----
    base.eval()
    acc_base = run_condition("base", items, lambda it: answer_mcq(base, tok, device, it))

    # ---- 挂载专家 ----
    router = [json.loads(l) for l in (args.experts / "router.jsonl").open(encoding="utf-8")]
    first = router[0]
    model = PeftModel.from_pretrained(base, args.experts / first["expert"], adapter_name=first["expert"])
    for e in router[1:]:
        model.load_adapter(args.experts / e["expert"], adapter_name=e["expert"])
    model.eval()
    keys = {e["expert"]: torch.load(e["key_path"], weights_only=True) for e in router}

    def best_expert(text):
        q = embed([text])[0]
        name, s = max(((n, (k @ q).max().item()) for n, k in keys.items()), key=lambda kv: kv[1])
        return name, s

    # ---- 2. 路由(真实用法) ----
    fired = 0

    def answer_router(it):
        nonlocal fired
        name, s = best_expert(it["q"])
        if s >= args.tau:
            fired += 1
            model.set_adapter(name)
            return answer_mcq(model, tok, device, it)
        with model.disable_adapter():
            return answer_mcq(model, tok, device, it)

    acc_router = run_condition("router", items, answer_router)
    print(f"  [router] 路由激活率 {fired}/{len(items)} ({fired / len(items):.1%})", flush=True)

    # ---- 3. 强制激活(最坏情况) ----
    def answer_forced(it):
        name, _ = best_expert(it["q"])
        model.set_adapter(name)
        return answer_mcq(model, tok, device, it)

    acc_forced = run_condition("forced", items, answer_forced)

    print(f"\n===== 汇总({args.model}) =====")
    print(f"base   {acc_base:.1%} | router {acc_router:.1%}(激活 {fired / len(items):.1%})"
          f" | forced {acc_forced:.1%}(退化 {acc_base - acc_forced:+.1%})")


if __name__ == "__main__":
    main()

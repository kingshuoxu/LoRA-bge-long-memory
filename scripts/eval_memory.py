"""G1 读取 + 评估:bge embedding 门控路由,测记忆准确率与选择性。

流程:加载基座 → 按 experts/router.jsonl 注册所有 LoRA adapter(不合并)→
每个问题用 bge-small-zh 编码,与各专家路由键做余弦相似度,≥ τ 才激活对应专家作答,否则用纯基座。

指标:
- 记忆准确率:各批次 QA 命中率(答案子串匹配);
- 选择性:常识问题误激活率(应≈0,此时输出=冻结基座,通用能力自然保持);
- --sweep:打印相似度分布用于标定 τ。

用法:
  python scripts/eval_memory.py --sweep            # 标定阈值
  python scripts/eval_memory.py --tau 0.5          # 正式评估
"""
import argparse
import json
import sys
from pathlib import Path

import torch
import torch.nn.functional as F
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

sys.path.insert(0, str(Path(__file__).parent))
from router import embed

MODEL = "models/Qwen2.5-0.5B-Instruct"


def pick_device(args) -> torch.device:
    """--cpu | --rocm | 默认 DirectML(按需导入,避免各后端环境互相污染)。"""
    if getattr(args, "cpu", False):
        return torch.device("cpu")
    if getattr(args, "rocm", False):
        return torch.device("cuda")
    import torch_directml
    return torch_directml.device()


def answer(model, tok, device, question: str, max_new_tokens: int = 50) -> str:
    # system prompt 与训练保持一致(FactDataset.SYSTEM)
    messages = [{"role": "system", "content": "你是助手。"},
                {"role": "user", "content": question + " 请简短回答。"}]
    text = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tok(text, return_tensors="pt").to(device)
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False,
                             pad_token_id=tok.eos_token_id)
    return tok.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tau", type=float, default=0.5, help="路由激活阈值")
    ap.add_argument("--sweep", action="store_true", help="只打印相似度分布,不评估")
    ap.add_argument("--n-per-batch", type=int, default=50)
    ap.add_argument("--skip", type=int, default=0, help="每批跳过前 N 条再取样(避开嵌套数据的前缀重叠)")
    ap.add_argument("--experts", type=Path, default=Path("experts"))
    ap.add_argument("--data", type=Path, default=Path("data"), help="数据目录(内含 batch_{N}.jsonl 与 generic_questions.jsonl)")
    ap.add_argument("--cpu", action="store_true")
    ap.add_argument("--rocm", action="store_true", help="用 ROCm/CUDA 设备推理")
    args = ap.parse_args()

    device = pick_device(args)
    tok = AutoTokenizer.from_pretrained(MODEL)
    base = AutoModelForCausalLM.from_pretrained(MODEL, torch_dtype=torch.float16).to(device)

    # 注册所有专家(每个 adapter 独立,不合并)
    router = [json.loads(l) for l in (args.experts / "router.jsonl").open(encoding="utf-8")]
    first = router[0]
    model = PeftModel.from_pretrained(base, args.experts / first["expert"], adapter_name=first["expert"])
    for e in router[1:]:
        model.load_adapter(args.experts / e["expert"], adapter_name=e["expert"])
    model.eval()
    keys = {e["expert"]: torch.load(e["key_path"], weights_only=True) for e in router}
    print(f"已注册专家: {list(keys)}, τ={args.tau}")

    def sims(text):
        q = embed([text])[0]
        # 每个专家内取最大相似度(检索式路由):问句命中任意一条事实即激活
        return {name: (k @ q).max().item() for name, k in keys.items()}

    # ---- 选择性:常识问题不应激活任何专家 ----
    generic = [json.loads(l)["q"] for l in open(args.data / "generic_questions.jsonl", encoding="utf-8")]
    false_fire = 0
    for q in generic:
        best, s = max(sims(q).items(), key=lambda kv: kv[1])
        if args.sweep:
            print(f"  [常识] sim={s:.3f} ({best}) | {q[:20]}")
        if s >= args.tau:
            false_fire += 1
    if not args.sweep:
        print(f"选择性: {len(generic) - false_fire}/{len(generic)} 未误激活 "
              f"(误激活率 {false_fire / len(generic):.0%})")

    # ---- 记忆准确率:逐批次测 QA ----
    for e in router:
        facts = [json.loads(l) for l in open(args.data / f"batch_{e['batch']}.jsonl", encoding="utf-8")]
        facts = facts[args.skip:args.skip + args.n_per_batch]
        if not facts:
            continue
        hit = fired = 0
        for f in facts:
            q, gold = f["qa"][0]["q"], f["qa"][0]["a"]
            best, s = max(sims(q).items(), key=lambda kv: kv[1])
            if args.sweep:
                match = "自家" if best == e["expert"] else "别家"
                print(f"  [批次{e['batch']}] sim={s:.3f} ({best},{match}) | {q[:20]}")
                continue
            if s >= args.tau:
                fired += 1
                model.set_adapter(best)
                ans = answer(model, tok, device, q)
            else:
                with model.disable_adapter():
                    ans = answer(model, tok, device, q)
            if gold.rstrip("年") in ans:
                hit += 1
        if not args.sweep:
            print(f"批次 {e['batch']}: 激活率 {fired}/{len(facts)}, "
                  f"记忆准确率 {hit}/{len(facts)} ({hit / len(facts):.0%})")


if __name__ == "__main__":
    main()

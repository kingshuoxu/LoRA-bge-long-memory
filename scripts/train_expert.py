"""G1 写入:为一个批次的虚构事实训练一个 LoRA 专家,并生成路由键。

- 冻结基座,只在每层 FFN(gate/up/down proj)挂新 LoRA,用事实陈述句做因果 LM 训练;
- 训练后:用基座(关闭 adapter)对所有陈述句取中间层隐向量,均值池化作为该专家的路由 key;
- 产出:experts/expert_{k}/(adapter 权重)+ experts/router.jsonl(key 文件路径、批次元信息)。

用法: python scripts/train_expert.py --batch 0 [--rank 16] [--epochs 20]
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import torch
from peft import LoraConfig, get_peft_model
from torch.utils.data import DataLoader, Dataset
from transformers import AutoModelForCausalLM, AutoTokenizer


def pick_device(args) -> torch.device:
    """--cpu | --rocm | 默认 DirectML(按需导入,避免各后端环境互相污染)。"""
    if getattr(args, "cpu", False):
        torch.set_num_threads(os.cpu_count() or 8)
        return torch.device("cpu")
    if getattr(args, "rocm", False):
        return torch.device("cuda")
    import torch_directml
    return torch_directml.device()

MODEL = "models/Qwen2.5-0.5B-Instruct"


class FactDataset(Dataset):
    """每条事实生成:1 条陈述句(全序列算 loss)+ 3 条 chat 格式 QA(只在答案上算 loss)。

    训练/评估格式对齐是关键:陈述句教"补全",QA 对教"被问到时能答出来"。
    system prompt 用短的,把序列长度砍半(CPU 训练的算子耗时与序列长成正比)。"""

    SYSTEM = "你是助手。"

    def __init__(self, facts, tok, max_len=128):
        self.rows = []  # (input_ids, labels)
        for f in facts:
            ids = tok(f["statement"], truncation=True, max_length=max_len)["input_ids"]
            self.rows.append((ids, ids.copy()))
            for qa in f["qa"]:
                prompt = tok.apply_chat_template(
                    [{"role": "system", "content": self.SYSTEM},
                     {"role": "user", "content": qa["q"]}],
                    tokenize=False, add_generation_prompt=True)
                p_ids = tok(prompt, add_special_tokens=False)["input_ids"]
                a_ids = tok(qa["a"] + "<|im_end|>\n", add_special_tokens=False)["input_ids"]
                self.rows.append((p_ids + a_ids, [-100] * len(p_ids) + a_ids))

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        return self.rows[i]


def collate(rows, pad_id):
    maxlen = max(len(r[0]) for r in rows)
    input_ids = torch.full((len(rows), maxlen), pad_id, dtype=torch.long)
    labels = torch.full((len(rows), maxlen), -100, dtype=torch.long)
    for i, (ids, lbl) in enumerate(rows):
        input_ids[i, :len(ids)] = torch.tensor(ids)
        labels[i, :len(lbl)] = torch.tensor(lbl)
    return input_ids, labels


def selective_loss(model, input_ids, labels):
    """只在监督位置计算 lm_head + CE,跳过 15 万词表的全量 logits(CPU 上单个 4s+ 的算子)。

    复刻 transformers 内部的 shift:logits[:, :-1] 对 labels[:, 1:]。"""
    causal_lm = model.get_base_model()  # 带 LoRA 注入的 Qwen2ForCausalLM
    hidden = causal_lm.model(input_ids=input_ids).last_hidden_state
    h = hidden[:, :-1, :]
    l = labels[:, 1:]
    mask = l != -100
    logits = causal_lm.lm_head(h[mask])  # (n_sup, vocab),n_sup 只有几百行
    return torch.nn.functional.cross_entropy(logits.float(), l[mask])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, required=True, help="数据批次号")
    ap.add_argument("--n-facts", type=int, default=0, help="只取前 N 条事实(0=全部,用于过拟合探针)")
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--bsz", type=int, default=16)
    ap.add_argument("--model", default="models/Qwen2.5-0.5B-Instruct", help="基座模型路径")
    ap.add_argument("--data", type=Path, default=Path("data"), help="数据目录(内含 batch_{N}.jsonl)")
    ap.add_argument("--out", type=Path, default=Path("experts"))
    ap.add_argument("--cpu", action="store_true",
                    help="用 CPU 训练(DirectML 的 fp32 前向有精度偏差,训练不可用;推理不受影响)")
    ap.add_argument("--rocm", action="store_true", help="用 ROCm/CUDA 设备训练")
    args = ap.parse_args()

    facts = [json.loads(l) for l in open(args.data / f"batch_{args.batch}.jsonl", encoding="utf-8")]
    if args.n_facts:
        facts = facts[:args.n_facts]
    print(f"批次 {args.batch}: {len(facts)} 条事实(训练样本 = 陈述句 + QA 对)", flush=True)

    device = pick_device(args)
    print(f"设备: {device}", flush=True)
    tok = AutoTokenizer.from_pretrained(args.model)
    # fp32 训练更稳(DirectML 对 bf16 支持有限);0.5B fp32 ≈ 2GB
    base = AutoModelForCausalLM.from_pretrained(args.model, torch_dtype=torch.float32).to(device)

    lcfg = LoraConfig(
        r=args.rank, lora_alpha=args.rank * 2, lora_dropout=0.0,
        target_modules=["gate_proj", "up_proj", "down_proj"],  # 记忆存进 FFN
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(base, lcfg)
    model.print_trainable_parameters()
    model.train()

    ds = FactDataset(facts, tok)
    dl = DataLoader(ds, batch_size=args.bsz, shuffle=True,
                    collate_fn=lambda r: collate(r, tok.eos_token_id))
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.0)  # 记忆任务:关掉 weight decay

    for epoch in range(args.epochs):
        total = 0.0
        t0 = time.perf_counter()
        for input_ids, labels in dl:
            input_ids, labels = input_ids.to(device), labels.to(device)
            loss = selective_loss(model, input_ids, labels)
            opt.zero_grad()
            loss.backward()
            opt.step()
            total += loss.item()
        dt = time.perf_counter() - t0
        if epoch % 5 == 0 or epoch == args.epochs - 1:
            print(f"epoch {epoch}: loss={total / len(dl):.4f} ({dt:.0f}s/epoch)", flush=True)

    expert_dir = args.out / f"expert_{args.batch}"
    expert_dir.mkdir(parents=True, exist_ok=True)
    # 路由键:每条事实单独一个 bge 向量(不按批求均值,均值会把实体信号稀释掉)
    sys.path.insert(0, str(Path(__file__).parent))
    from router import embed
    key_texts = []
    for f in facts:
        key_texts.append(f["statement"])
        key_texts.extend(qa["q"] for qa in f["qa"])
    key = embed(key_texts)  # (n_texts, dim),已归一化
    torch.save(key, expert_dir / "router_key.pt")

    # DirectML 张量是不透明的,safetensors 无法读取其 storage,必须先搬到 CPU 再保存
    model.to("cpu")
    model.save_pretrained(expert_dir)

    # 路由表:同批次重训时去重,避免 eval 重复注册同名 adapter
    router_entry = {
        "expert": f"expert_{args.batch}",
        "batch": args.batch,
        "n_facts": len(facts),
        "rank": args.rank,
        "key_path": str(expert_dir / "router_key.pt"),
    }
    router_path = args.out / "router.jsonl"
    entries = []
    if router_path.exists():
        entries = [json.loads(l) for l in router_path.open(encoding="utf-8")]
        entries = [e for e in entries if e["batch"] != args.batch]
    entries.append(router_entry)
    entries.sort(key=lambda e: e["batch"])
    with router_path.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    print(f"专家已保存到 {expert_dir},路由键已登记")


if __name__ == "__main__":
    main()

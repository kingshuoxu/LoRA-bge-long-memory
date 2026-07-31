"""检查 FactDataset 的样本构造:解码训练样本 + 监督区段 + 每类样本的 loss。"""
import json
import sys
from pathlib import Path

import torch
import torch_directml
from peft import LoraConfig, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from train_expert import FactDataset

MODEL = "models/Qwen2.5-1.5B-Instruct"

facts = [json.loads(l) for l in open("data/batch_0.jsonl", encoding="utf-8")][:2]
tok = AutoTokenizer.from_pretrained(MODEL)
ds = FactDataset(facts, tok)

print(f"样本数: {len(ds)} (2 条事实 × 4)")
for i, (ids, lbl) in enumerate(ds.rows):
    print(f"\n--- 样本 {i} ({len(ids)} tokens) ---")
    print("解码:", repr(tok.decode(ids)))
    sup = [t for t, l in zip(ids, lbl) if l != -100]
    print("监督区段:", repr(tok.decode(sup)))

# 每类样本单独算 loss
device = torch_directml.device()
base = AutoModelForCausalLM.from_pretrained(MODEL, torch_dtype=torch.float32).to(device)
model = get_peft_model(base, LoraConfig(
    r=16, lora_alpha=32, lora_dropout=0.0,
    target_modules=["gate_proj", "up_proj", "down_proj"], task_type="CAUSAL_LM"))
model.eval()
with torch.no_grad():
    for i, (ids, lbl) in enumerate(ds.rows[:4]):
        ii = torch.tensor([ids]).to(device)
        ll = torch.tensor([lbl]).to(device)
        loss = model(input_ids=ii, labels=ll).loss
        print(f"样本 {i} loss = {loss.item():.4f}")

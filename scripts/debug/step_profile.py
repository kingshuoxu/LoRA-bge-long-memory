"""CPU 单步分步计时:定位 75s/步 的瓶颈到底在前向、反向、loss 还是优化器。"""
import json
import sys
import time
from pathlib import Path

import torch
from peft import LoraConfig, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from train_expert import FactDataset, collate

MODEL = "models/Qwen2.5-1.5B-Instruct"
BSZ = 32

torch.set_num_threads(16)
tok = AutoTokenizer.from_pretrained(MODEL)
facts = [json.loads(l) for l in open("data/batch_0.jsonl", encoding="utf-8")][:8]
ds = FactDataset(facts, tok)
rows = [ds.rows[i] for i in range(0, BSZ)]
input_ids, labels = collate(rows, tok.eos_token_id)
print(f"batch: input_ids {tuple(input_ids.shape)}")

t0 = time.perf_counter()
base = AutoModelForCausalLM.from_pretrained(MODEL, torch_dtype=torch.float32)
t1 = time.perf_counter()
print(f"模型加载: {t1 - t0:.1f}s")

model = get_peft_model(base, LoraConfig(
    r=32, lora_alpha=64, lora_dropout=0.0,
    target_modules=["gate_proj", "up_proj", "down_proj"], task_type="CAUSAL_LM"))
model.train()
opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad],
                        lr=1e-3, weight_decay=0.0)

for step in range(2):
    t0 = time.perf_counter()
    out = model(input_ids=input_ids, labels=labels)
    t1 = time.perf_counter()
    loss = out.loss
    t2 = time.perf_counter()
    opt.zero_grad()
    loss.backward()
    t3 = time.perf_counter()
    opt.step()
    t4 = time.perf_counter()
    print(f"step {step}: loss={loss.item():.3f} | 前向(含loss) {t1-t0:.2f}s | "
          f"loss取值 {t2-t1:.2f}s | 反向 {t3-t2:.2f}s | 优化器 {t4-t3:.2f}s | 总 {t4-t0:.2f}s")

# 单独拆一次:不带 labels 的纯前向 vs 带 labels
with torch.no_grad():
    t0 = time.perf_counter()
    model(input_ids=input_ids)
    t1 = time.perf_counter()
    print(f"纯前向(无 labels, 无 logits CE 计算): {t1-t0:.2f}s")

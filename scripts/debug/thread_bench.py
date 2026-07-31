"""CPU 线程配置对比:同一 batch 的前向,测不同线程数下的速度。"""
import json
import os
import sys
import time
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from train_expert import FactDataset, collate
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL = "models/Qwen2.5-1.5B-Instruct"
torch.set_num_interop_threads(1)

tok = AutoTokenizer.from_pretrained(MODEL)
facts = [json.loads(l) for l in open("data/batch_0.jsonl", encoding="utf-8")][:8]
ds = FactDataset(facts, tok)
input_ids, _ = collate([ds.rows[i] for i in range(32)], tok.eos_token_id)

model = AutoModelForCausalLM.from_pretrained(MODEL, torch_dtype=torch.float32)
model.eval()

for n in [16, 10, 8, 6, 4]:
    torch.set_num_threads(n)
    with torch.no_grad():
        model(input_ids)  # warmup
        t0 = time.perf_counter()
        model(input_ids)
        dt = time.perf_counter() - t0
    print(f"threads={n:2d}: 前向 {dt:.2f}s ({input_ids.numel() / dt:.0f} tok/s)")

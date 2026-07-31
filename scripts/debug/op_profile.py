"""torch.profiler 定位 CPU 前向的热点算子。"""
import json
import sys
from pathlib import Path

import torch
from torch.profiler import ProfilerActivity, profile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from train_expert import FactDataset, collate
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL = "models/Qwen2.5-1.5B-Instruct"
torch.set_num_threads(16)

tok = AutoTokenizer.from_pretrained(MODEL)
facts = [json.loads(l) for l in open("data/batch_0.jsonl", encoding="utf-8")][:8]
ds = FactDataset(facts, tok)
input_ids, _ = collate([ds.rows[i] for i in range(32)], tok.eos_token_id)

model = AutoModelForCausalLM.from_pretrained(MODEL, torch_dtype=torch.float32)
model.eval()

with torch.no_grad():
    model(input_ids)  # warmup
    with profile(activities=[ProfilerActivity.CPU], with_stack=False) as prof:
        model(input_ids)

print(prof.key_averages().table(sort_by="self_cpu_time_total", row_limit=15,
                                max_name_column_width=60))

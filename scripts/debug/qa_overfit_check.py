"""单 QA 样本过拟合:同一条 QA 重复 10 步,看 loss 能否下降。"""
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

USE_CPU = "--cpu" in sys.argv
USE_FP16 = "--fp16" in sys.argv
USE_EAGER = "--eager" in sys.argv

facts = [json.loads(l) for l in open("data/batch_0.jsonl", encoding="utf-8")][:1]
tok = AutoTokenizer.from_pretrained(MODEL)
ds = FactDataset(facts, tok)
ids, lbl = ds.rows[1]  # 第一条 QA 样本
print("样本:", repr(tok.decode(ids)))

device = torch.device("cpu") if USE_CPU else torch_directml.device()
dtype = torch.float16 if USE_FP16 else torch.float32
print("设备:", "CPU" if USE_CPU else f"DirectML ({dtype})")
attn_impl = "eager" if USE_EAGER else "sdpa"
base = AutoModelForCausalLM.from_pretrained(MODEL, torch_dtype=dtype, attn_implementation=attn_impl).to(device)
model = get_peft_model(base, LoraConfig(
    r=16, lora_alpha=32, lora_dropout=0.0,
    target_modules=["gate_proj", "up_proj", "down_proj"], task_type="CAUSAL_LM"))
model.train()
trainable = [p for n, p in model.named_parameters() if "lora_" in n]
opt = torch.optim.AdamW(trainable, lr=1e-3, weight_decay=0.0)

ii = torch.tensor([ids]).to(device)
ll = torch.tensor([lbl]).to(device)
for step in range(15):
    loss = model(input_ids=ii, labels=ll).loss
    opt.zero_grad()
    loss.backward()
    opt.step()
    print(f"step {step}: loss={loss.item():.4f}")

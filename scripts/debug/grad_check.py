"""梯度流检查:一次前向+反向,看 LoRA 参数是否真的收到梯度。"""
import torch
import torch_directml
from peft import LoraConfig, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL = "models/Qwen2.5-1.5B-Instruct"

device = torch_directml.device()
tok = AutoTokenizer.from_pretrained(MODEL)
base = AutoModelForCausalLM.from_pretrained(MODEL, torch_dtype=torch.float32).to(device)
model = get_peft_model(base, LoraConfig(
    r=16, lora_alpha=32, lora_dropout=0.0,
    target_modules=["gate_proj", "up_proj", "down_proj"], task_type="CAUSAL_LM"))
model.train()

text = "塔佐巴洛公司成立于1978年。"
ids = tok(text, return_tensors="pt").to(device)
loss = model(**ids, labels=ids["input_ids"]).loss
print(f"loss = {loss.item():.4f}, is_nan = {torch.isnan(loss).item()}")
loss.backward()

for name, p in model.named_parameters():
    if "lora_" in name:
        if p.grad is None:
            print(f"{name}: grad=None")
        else:
            g = p.grad
            print(f"{name}: norm={g.norm().item():.6f}, nan={torch.isnan(g).any().item()}, "
                  f"abs_max={g.abs().max().item():.6e}")
        # 只看前 4 个
        if "layers.3." in name:
            break

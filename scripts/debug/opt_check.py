"""优化器检查:AdamW / SGD 各走两步,看 LoRA 参数是否真的在更新。"""
import torch
import torch_directml
from peft import LoraConfig, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL = "models/Qwen2.5-1.5B-Instruct"


def run(opt_name):
    device = torch_directml.device()
    tok = AutoTokenizer.from_pretrained(MODEL)
    base = AutoModelForCausalLM.from_pretrained(MODEL, torch_dtype=torch.float32).to(device)
    model = get_peft_model(base, LoraConfig(
        r=16, lora_alpha=32, lora_dropout=0.0,
        target_modules=["gate_proj", "up_proj", "down_proj"], task_type="CAUSAL_LM"))
    model.train()
    trainable = [p for n, p in model.named_parameters() if "lora_" in n]
    if opt_name == "adamw":
        opt = torch.optim.AdamW(trainable, lr=1e-3, weight_decay=0.0)
    else:
        opt = torch.optim.SGD(trainable, lr=1e-2, momentum=0.9)

    ids = tok("塔佐巴洛公司成立于1978年。", return_tensors="pt").to(device)
    for step in range(2):
        before = [p.detach().clone() for p in trainable]
        loss = model(**ids, labels=ids["input_ids"]).loss
        opt.zero_grad()
        loss.backward()
        opt.step()
        deltas = [(p.detach() - b).norm().item() for p, b in zip(trainable, before)]
        moved = sum(d > 0 for d in deltas)
        print(f"  [{opt_name}] step {step}: loss={loss.item():.4f}, "
              f"参数有变化的 {moved}/{len(deltas)}, 平均 delta={sum(deltas)/len(deltas):.3e}")


for name in ["sgd", "adamw"]:
    run(name)

"""surprise 自动写入门:输入流 → 判定 → 缓冲 → 自动训练新专家。

判定逻辑(校准结论见 docs/experiment-results.md §9,AUC 0.876 不可硬分,走降级方案):
1. 路由检查:与已有专家键 max-sim ≥ τ → 已记住,跳过(防重复写入);
2. surprise 检查:基座逐 token loss < SKIP_LOSS(2.5)→ 基座显然已知,跳过(保守,
   只挡"确定不用写的",校准显示此阈值对事实召回损失 ~2%);
3. 其余视为"用户显式告知的新知"(对话/文档流场景)→ 进缓冲,攒满 N 条触发训练。

训练通过子进程调 train_expert.py(隔离干净、复用已验证代码,含路由登记)。
缓冲内按 statement 文本去重(同一事实在训练前重复出现只留一份)。

用法见 scripts/auto_write_demo.py。
"""
import json
import subprocess
import sys
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

sys.path.insert(0, str(Path(__file__).parent))
from router import embed
from calibrate_surprise import mean_token_loss

MODEL = "models/Qwen2.5-0.5B-Instruct"
SKIP_LOSS = 2.5    # 基座 loss 低于此 → 显然已知,不写
DEDUP_SIM = 0.94   # 去重阈值,取自实测间隙:同模板跨事实最高 sim=0.921,精确重复=1.0
                   # (阈值 0.85 会误杀 50.8% 事实;0.93+ 误杀 0%。读取侧 argmax 路由仍用 τ=0.5)


class AutoWriter:
    def __init__(self, experts_dir="experts_auto", data_dir="data_auto",
                 buffer_size=50, device="cuda", venv_python=".venv-rocm/Scripts/python.exe",
                 epochs=21, lr=5e-4, bsz=64):
        self.experts_dir = Path(experts_dir)
        self.data_dir = Path(data_dir)
        self.buffer_size = buffer_size
        self.device = torch.device(device)
        self.venv_python = venv_python
        self.train_args = dict(epochs=epochs, lr=lr, bsz=bsz)
        self.buffer: list[dict] = []
        self._buf_texts: set[str] = set()
        self.next_batch = 0
        self.decisions: list[dict] = []  # 审计日志

        self.tok = AutoTokenizer.from_pretrained(MODEL)
        if self.tok.pad_token_id is None:
            self.tok.pad_token = self.tok.eos_token
        self.base = AutoModelForCausalLM.from_pretrained(MODEL, torch_dtype=torch.float32).to(self.device)
        self.base.eval()
        self._load_router()

    def _load_router(self):
        """加载已有专家键(训练后需重新调用)。"""
        self.keys: dict[str, torch.Tensor] = {}
        rpath = self.experts_dir / "router.jsonl"
        if rpath.exists():
            for line in rpath.open(encoding="utf-8"):
                e = json.loads(line)
                self.keys[e["expert"]] = torch.load(e["key_path"], weights_only=True)
                self.next_batch = max(self.next_batch, e["batch"] + 1)

    def _route_sim(self, text: str) -> float:
        if not self.keys:
            return 0.0
        q = embed([text])[0]
        return max((k @ q).max().item() for k in self.keys.values())

    def observe(self, fact: dict) -> dict:
        """喂入一条流元素。fact 至少含 statement;若含 qa 则训练时用 QA 对(推荐)。

        返回判定记录:{action: skip_memorized|skip_known|buffered|trained, ...}"""
        text = fact["statement"]

        if text in self._buf_texts:
            d = {"action": "skip_buffered_dup", "text": text}
        else:
            sim = self._route_sim(text)
            if sim >= DEDUP_SIM:
                d = {"action": "skip_memorized", "text": text, "sim": round(sim, 3)}
            else:
                loss = mean_token_loss(self.base, self.tok, self.device, [text]).item()
                if loss < SKIP_LOSS:
                    d = {"action": "skip_known", "text": text, "loss": round(loss, 3),
                         "sim": round(sim, 3)}
                else:
                    self.buffer.append(fact)
                    self._buf_texts.add(text)
                    d = {"action": "buffered", "text": text, "loss": round(loss, 3),
                         "sim": round(sim, 3), "buffer": len(self.buffer)}
        self.decisions.append(d)
        if len(self.buffer) >= self.buffer_size:
            self.flush()
        return d

    def flush(self):
        """把缓冲训练成一个新专家并更新路由。"""
        if not self.buffer:
            return
        batch = self.next_batch
        self.data_dir.mkdir(parents=True, exist_ok=True)
        path = self.data_dir / f"batch_{batch}.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for fact in self.buffer:
                f.write(json.dumps(fact, ensure_ascii=False) + "\n")
        n = len(self.buffer)
        self.buffer, self._buf_texts = [], set()

        a = self.train_args
        cmd = [self.venv_python, "scripts/train_expert.py", "--batch", str(batch),
               "--data", str(self.data_dir), "--out", str(self.experts_dir),
               "--rocm", "--rank", "32", "--lr", str(a["lr"]),
               "--epochs", str(a["epochs"]), "--bsz", str(a["bsz"])]
        print(f"[AutoWriter] 缓冲满,训练专家 batch={batch}({n} 条事实)...", flush=True)
        subprocess.run(cmd, check=True,
                       stdout=subprocess.DEVNULL)  # 训练日志静默,错误仍会抛出
        self._load_router()  # 登记新键,后续 observe 能识别这批已记忆
        print(f"[AutoWriter] 专家 {batch} 已上线", flush=True)
        self.decisions.append({"action": "trained", "batch": batch, "n_facts": n})

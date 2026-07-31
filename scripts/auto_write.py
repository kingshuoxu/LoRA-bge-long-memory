"""surprise 自动写入门 V2:输入流 → 判定 → 缓冲 → 自动训练新专家。

判定逻辑(校准见 docs/experiment-results.md §9 与 calibrate_qa_gate.py):
1. 路由去重:与已有专家键 max-sim ≥ 0.94 → 已记住,跳过(阈值取自实测间隙
   [0.921, 1.0],不能与读取侧 τ=0.5 混用);
2. QA 自答(主信号):条目带 qa 时,让基座自答 qa[0],答对 = 已知 = 跳过,
   答错才写(0.5B 校准:事实召回 100%,常识误写 16%;perplexity 信号为 72%);
3. perplexity 兜底:无 qa 的纯陈述,基座 loss < 2.5 → 显然已知,跳过。

训练通过子进程调 train_expert.py;缓冲内按 statement 文本去重。

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
from calibrate_qa_gate import self_answer, _norm

MODEL = "models/Qwen2.5-0.5B-Instruct"
SKIP_LOSS = 2.5    # 无 qa 条目的 perplexity 兜底阈值
DEDUP_SIM = 0.94   # 去重阈值,取自实测间隙:同模板跨事实最高 sim=0.921,精确重复=1.0


class AutoWriter:
    def __init__(self, experts_dir="experts_auto", data_dir="data_auto",
                 buffer_size=50, device="cuda", venv_python=".venv-rocm/Scripts/python.exe",
                 epochs=21, lr=5e-4, bsz=64, model=MODEL):
        self.experts_dir = Path(experts_dir)
        self.data_dir = Path(data_dir)
        self.buffer_size = buffer_size
        self.device = torch.device(device)
        self.venv_python = venv_python
        self.train_args = dict(epochs=epochs, lr=lr, bsz=bsz)
        self.model = model
        self.buffer: list[dict] = []
        self._buf_texts: set[str] = set()
        self.next_batch = 0
        self.decisions: list[dict] = []  # 审计日志

        self.tok = AutoTokenizer.from_pretrained(self.model)
        if self.tok.pad_token_id is None:
            self.tok.pad_token = self.tok.eos_token
        self.base = AutoModelForCausalLM.from_pretrained(self.model, torch_dtype=torch.float32).to(self.device)
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
            elif fact.get("qa"):
                # 主信号:基座自答,答对=已知=跳过(答错才写)
                q, gold = fact["qa"][0]["q"], fact["qa"][0]["a"]
                ans = self_answer(self.base, self.tok, self.device, q)
                if _norm(gold.rstrip("年")) in _norm(ans):
                    d = {"action": "skip_known_qa", "text": text, "sim": round(sim, 3),
                         "ans": ans[:30]}
                else:
                    self.buffer.append(fact)
                    self._buf_texts.add(text)
                    d = {"action": "buffered", "text": text, "sim": round(sim, 3),
                         "buffer": len(self.buffer)}
            else:
                # 兜底:无 qa 的纯陈述用 perplexity
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
               "--epochs", str(a["epochs"]), "--bsz", str(a["bsz"]),
               "--model", self.model]
        print(f"[AutoWriter] 缓冲满,训练专家 batch={batch}({n} 条事实)...", flush=True)
        subprocess.run(cmd, check=True,
                       stdout=subprocess.DEVNULL)  # 训练日志静默,错误仍会抛出
        self._load_router()  # 登记新键,后续 observe 能识别这批已记忆
        print(f"[AutoWriter] 专家 {batch} 已上线", flush=True)
        self.decisions.append({"action": "trained", "batch": batch, "n_facts": n})

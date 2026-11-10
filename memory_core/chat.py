"""挂上路由选中的 LoRA 再生成。没有专家或守卫拦住时用基座。"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from memory_core.device import infer_dtype, pick_device
from memory_core.prompts import has_cjk, system_for, with_brief
from memory_core.routing import RouteDecision
from memory_core.store import ExpertRecord, weights_ready


class ChatEngine:
    def __init__(self, model_path: Path, device_name: str | None = None):
        self.model_path = Path(model_path)
        self.device = pick_device(device_name)
        self.dtype = infer_dtype(self.device)
        self.tok = None
        self.model = None
        self._peft = False
        self._loaded: set[str] = set()
        self._load_lock = threading.Lock()

    def _weights_ready(self) -> bool:
        if self.model is None:
            return False
        for param in self.model.parameters():
            if getattr(param, "is_meta", False) or getattr(param.device, "type", "") == "meta":
                return False
        return True

    def ensure(self) -> None:
        if self._weights_ready():
            return
        from memory_core.model_load import LOAD_LOCK

        with LOAD_LOCK, self._load_lock:
            if self._weights_ready():
                return
            self.model = None
            self.tok = AutoTokenizer.from_pretrained(self.model_path)
            if self.tok.pad_token_id is None:
                self.tok.pad_token = self.tok.eos_token
            # 不用 accelerate 的 meta 空权重。升级后第一次请求和预热会同时进来，
            # 锁住这一段，等权重真正落到 cpu 再给别人用。
            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_path,
                torch_dtype=self.dtype,
                low_cpu_mem_usage=False,
                device_map=None,
            )
            self.model.to(self.device)
            if not self._weights_ready():
                self.model = None
                raise RuntimeError("模型权重没有落到 cpu")
            self.model.eval()
            self._peft = False
            self._loaded = set()

    def unload(self) -> None:
        self.model = None
        self.tok = None
        self._peft = False
        self._loaded = set()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def sync_adapters(self, experts: list[ExpertRecord]) -> None:
        self.ensure()
        wanted = []
        for expert in experts:
            if weights_ready(expert.directory):
                wanted.append(expert)
        if not wanted:
            return
        from peft import PeftModel

        for expert in wanted:
            if expert.name in self._loaded:
                continue
            if not self._peft:
                self.model = PeftModel.from_pretrained(
                    self.model, str(expert.directory), adapter_name=expert.name
                )
                self._peft = True
            else:
                self.model.load_adapter(str(expert.directory), adapter_name=expert.name)
            self._loaded.add(expert.name)
        self.model.eval()

    def reply(
        self,
        history: list[dict],
        decision: RouteDecision,
        max_new_tokens: int = 256,
        hint: str = "",
        max_seconds: float | None = None,
    ) -> str:
        self.ensure()
        trimmed = history[-12:]
        last_user = ""
        for message in reversed(trimmed):
            if message["role"] == "user":
                last_user = message["content"]
                break
        messages = [{"role": "system", "content": system_for(last_user)}]
        if hint:
            messages.append({"role": "system", "content": hint})
        for index, message in enumerate(trimmed):
            content = message["content"]
            if index == len(trimmed) - 1 and message["role"] == "user":
                content = with_brief(content)
            messages.append({"role": message["role"], "content": content})
        rendered = self.tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self.tok(rendered, return_tensors="pt", truncation=True, max_length=1024).to(self.device)
        im_end = self.tok.convert_tokens_to_ids("<|im_end|>")
        eos = [self.tok.eos_token_id]
        if isinstance(im_end, int) and im_end >= 0:
            eos.append(im_end)
        use_adapter = bool(decision.fired and decision.expert and decision.expert in self._loaded)

        def _generate():
            kwargs = {
                "max_new_tokens": max_new_tokens,
                "do_sample": False,
                "pad_token_id": self.tok.eos_token_id,
                "eos_token_id": eos,
            }
            if max_seconds and max_seconds > 0:
                from transformers import StoppingCriteria, StoppingCriteriaList

                class _Wall(StoppingCriteria):
                    def __init__(self, seconds: float):
                        self.deadline = time.monotonic() + seconds

                    def __call__(self, input_ids, scores, **kwargs):
                        return bool(time.monotonic() >= self.deadline)

                kwargs["stopping_criteria"] = StoppingCriteriaList([_Wall(max_seconds)])
            with torch.no_grad():
                out = self.model.generate(**inputs, **kwargs)
            return _finish_sentence(self.tok.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip())

        if use_adapter:
            self.model.set_adapter(decision.expert)
            return _generate()
        if self._peft:
            with self.model.disable_adapter():
                return _generate()
        return _generate()

    def complete_base(self, system: str, user: str, max_new_tokens: int = 32) -> str:
        """基座摘录。不挂 LoRA，避免用权重把没写过的答案补出来。"""
        self.ensure()
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        rendered = self.tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self.tok(rendered, return_tensors="pt", truncation=True, max_length=1024).to(self.device)
        im_end = self.tok.convert_tokens_to_ids("<|im_end|>")
        eos = [self.tok.eos_token_id]
        if isinstance(im_end, int) and im_end >= 0:
            eos.append(im_end)

        def _generate() -> str:
            with torch.no_grad():
                out = self.model.generate(
                    **inputs,
                    max_new_tokens=max_new_tokens,
                    do_sample=False,
                    pad_token_id=self.tok.eos_token_id,
                    eos_token_id=eos,
                )
            return self.tok.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()

        if self._peft:
            with self.model.disable_adapter():
                return _generate()
        return _generate()


def _finish_sentence(text: str) -> str:
    """生成被长度截断时，停在句末或词边界，不把半个词留给界面。"""
    text = (text or "").strip()
    if not text or text[-1] in "。！？.!?…":
        return text
    cut = max(text.rfind(mark) for mark in "。！？.!?")
    if cut >= 12:
        return text[: cut + 1]
    if has_cjk(text):
        return text + "…"
    if " " in text:
        return text.rsplit(" ", 1)[0].rstrip() + "…"
    return text + "…"

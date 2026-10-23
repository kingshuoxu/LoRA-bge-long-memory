"""挂上路由选中的 LoRA 再生成。没有专家或守卫拦住时用基座。"""
from __future__ import annotations

from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from memory_core.device import infer_dtype, pick_device
from memory_core.prompts import system_for, with_brief
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

    def ensure(self) -> None:
        if self.model is not None:
            return
        self.tok = AutoTokenizer.from_pretrained(self.model_path)
        if self.tok.pad_token_id is None:
            self.tok.pad_token = self.tok.eos_token
        self.model = AutoModelForCausalLM.from_pretrained(self.model_path, torch_dtype=self.dtype)
        self.model.to(self.device)
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

    def reply(self, history: list[dict], decision: RouteDecision, max_new_tokens: int = 80, hint: str = "") -> str:
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
            with torch.no_grad():
                out = self.model.generate(
                    **inputs,
                    max_new_tokens=max_new_tokens,
                    do_sample=False,
                    pad_token_id=self.tok.eos_token_id,
                    eos_token_id=eos,
                )
            return self.tok.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()

        if use_adapter:
            self.model.set_adapter(decision.expert)
            return _generate()
        if self._peft:
            with self.model.disable_adapter():
                return _generate()
        return _generate()

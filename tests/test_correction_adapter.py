"""Keep pending adapters disabled at generation, even when previously loaded."""
from contextlib import contextmanager
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import torch

from memory_core.chat import ChatEngine
from memory_core.routing import RouteDecision


class FakeModel:
    def __init__(self):
        self.active = "stale"
        self.selected = []
        self.loaded = []
        self.generated_with = []

    def parameters(self):
        return iter(())

    def eval(self):
        return self

    def load_adapter(self, path, adapter_name):
        self.loaded.append(adapter_name)

    def set_adapter(self, name):
        self.selected.append(name)
        self.active = name

    @contextmanager
    def disable_adapter(self):
        previous, self.active = self.active, None
        try:
            yield
        finally:
            self.active = previous

    def generate(self, **kwargs):
        self.generated_with.append(self.active)
        return torch.tensor([[1, 2]])


class FakeInputs(dict):
    def to(self, device):
        return self


class FakeTokenizer:
    eos_token_id = 0

    def apply_chat_template(self, messages, **kwargs):
        return "prompt"

    def __call__(self, text, **kwargs):
        return FakeInputs(input_ids=torch.tensor([[1]]))

    def convert_tokens_to_ids(self, token):
        return 0

    def decode(self, tokens, **kwargs):
        return "Answer."


class CorrectionAdapterTests(unittest.TestCase):
    def test_pending_adapter_not_loaded_selected_or_used_but_unrelated_is(self):
        with TemporaryDirectory() as directory:
            engine = ChatEngine(Path(directory), "cpu")
            engine.model = model = FakeModel()
            engine.tok = FakeTokenizer()
            engine._peft = True
            engine._loaded = {"stale"}
            experts = [
                SimpleNamespace(name=name, directory=Path(directory) / name, correction_pending=pending)
                for name, pending in (("stale", True), ("pending_unloaded", True), ("unrelated", False))
            ]
            with patch("memory_core.chat.weights_ready", return_value=True), patch.dict(
                sys.modules, {"peft": SimpleNamespace(PeftModel=object())}
            ):
                engine.sync_adapters(experts)
            self.assertEqual(model.loaded, ["unrelated"])
            history = [{"role": "user", "content": "What is remembered?"}]
            for name in ("stale", "pending_unloaded", "unrelated"):
                engine.reply(history, RouteDecision(True, name, 1.0, name, "test", True, True))
            self.assertEqual(model.selected, ["unrelated"])
            self.assertEqual(model.generated_with, [None, None, "unrelated"])


    def test_ready_same_name_reloads_cached_adapter_before_reenabling(self):
        with TemporaryDirectory() as directory:
            engine = ChatEngine(Path(directory), "cpu")
            engine.model = stale_model = FakeModel()
            engine.tok = FakeTokenizer()
            engine._peft = True
            engine._loaded = {"stale"}
            expert = SimpleNamespace(name="stale", directory=Path(directory), correction_pending=True)

            fresh_model = FakeModel()

            def ensure_fake():
                if engine.model is None:
                    engine.model = fresh_model
                    engine.tok = FakeTokenizer()

            def fake_peft_load(model, path, adapter_name):
                self.assertIs(model, fresh_model)
                model.loaded.append(adapter_name)
                return model

            with patch("memory_core.chat.weights_ready", return_value=True), patch.object(
                engine, "ensure", side_effect=ensure_fake
            ), patch.dict(
                sys.modules, {"peft": SimpleNamespace(PeftModel=SimpleNamespace(from_pretrained=fake_peft_load))}
            ):
                engine.sync_adapters([expert])
                engine.sync_adapters([])  # Registration may temporarily hide the expert.
                engine.reply([{"role": "user", "content": "Query?"}],
                             RouteDecision(True, "stale", 1.0, "stale", "test", True, True))
                self.assertEqual(stale_model.generated_with, [None])
                expert.correction_pending = False
                engine.sync_adapters([expert])
                engine.reply([{"role": "user", "content": "Query again?"}],
                             RouteDecision(True, "stale", 1.0, "stale", "test", True, True))
            self.assertEqual(stale_model.selected, [])
            self.assertEqual(fresh_model.loaded, ["stale"])
            self.assertEqual(fresh_model.generated_with, ["stale"])

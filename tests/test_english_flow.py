"""英文对话：抽出事实、巩固、回忆，并确认提问不会被当成纠正。"""
from __future__ import annotations

import os
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path

from memory_core.paths import default_models_dir


TURNS = [
    "Mira Chen's cat's name is Snow.",
    "Mira Chen lives in Qinglan.",
    "Mira Chen's bicycle color is vermilion.",
]
PRIMARY = [
    ("What is Mira Chen's cat's name?", "Snow"),
    ("Where does Mira Chen live?", "Qinglan"),
    ("What is Mira Chen's bicycle color?", "vermilion"),
]
PARAPHRASE = ("What is the cat's name of Mira Chen?", "Snow")


def _models() -> Path:
    path = default_models_dir()
    if not (path / "Qwen2.5-0.5B-Instruct").is_dir() or not (path / "bge-small-zh-v1.5").is_dir():
        raise unittest.SkipTest("没有本地模型")
    return path


def _hit(answer: str, gold: str) -> bool:
    return gold.replace(" ", "").lower() in answer.replace(" ", "").lower()


class EnglishFlowTests(unittest.TestCase):
    def test_consolidate_and_recall(self):
        from memory_core.e2e_check import _wait
        from memory_core.service import MemoryService

        models = _models()
        kept = os.environ.get("LORA_EN_HOME")
        if kept:
            home = Path(kept)
            if home.exists():
                import shutil
                shutil.rmtree(home)
            home.mkdir(parents=True)
            context = nullcontext(str(home))
        else:
            context = tempfile.TemporaryDirectory(prefix="lora-en-")
        with context as tmp:
            home = Path(tmp)
            service = MemoryService(home=home, models_dir=models, repo_experts=None, device="cpu", use_repo_experts=False)
            service.ensure_ready()
            conv = service.create_conversation("Mira Chen")
            for turn in TURNS:
                result = service.send_message(conv["id"], turn)
                self.assertFalse(result["route"]["fired"], turn)
            preview = service.preview_consolidation([conv["id"]])
            values = {fact["value"] for fact in preview["facts"] if fact.get("selected")}
            self.assertTrue({"Snow", "Qinglan", "vermilion"} <= values, values)
            selected = [fact for fact in preview["facts"] if fact.get("selected") and fact["value"] in {"Snow", "Qinglan", "vermilion"}]
            job = service.start_consolidation([conv["id"]], selected)
            status = _wait(service, job["id"], timeout=2400)
            self.assertEqual(status.get("status"), "done", status.get("error") or status.get("message"))
            expert = status["expert"]
            fresh = service.create_conversation("Recall")
            for question, gold in PRIMARY:
                result = service.send_message(fresh["id"], question)
                answer = result["assistant"]["content"]
                route = result["route"]
                self.assertTrue(route["fired"] and route["expert"] == expert, (question, route, answer))
                self.assertTrue(_hit(answer, gold), (question, answer))
                print(f"Q: {question}\nA: {answer}\n", flush=True)
                trace = result.get("recall") or {}
                self.assertTrue(trace.get("mounted"), trace)
                self.assertTrue(any(gold == fact.get("value") or gold in str(fact.get("value")) for fact in trace.get("matched_facts") or []), trace.get("matched_facts"))
            question, gold = PARAPHRASE
            result = service.send_message(fresh["id"], question)
            self.assertTrue(result["route"]["fired"], result["route"])
            self.assertTrue(_hit(result["assistant"]["content"], gold), result["assistant"]["content"])
            proposal = service.propose_correction("Mira Chen lives in Starport, not Qinglan.")
            self.assertIsNotNone(proposal)
            self.assertEqual(proposal["new_value"], "Starport")
            self.assertEqual(proposal["old_value"], "Qinglan")
            self.assertIsNone(service.propose_correction("Where does Mira Chen live?"))
            print(f"EN_HOME {home}", flush=True)


if __name__ == "__main__":
    unittest.main()

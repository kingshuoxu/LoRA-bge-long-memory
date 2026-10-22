"""路由对照：旧专家与 eval_memory 的 top-1 判定一致；删除后不交叉误射。"""
import json
import shutil
import unittest
from pathlib import Path

from memory_core.paths import ensure_scripts_path
from memory_core.routing import bind_bge, legacy_top1, route_text
from memory_core.store import load_experts

ROOT = Path(__file__).resolve().parents[1]
GATE = {"tau": 0.6, "fact_tau": 0.6, "dedup_sim": 0.94}


def models_dir() -> Path:
    candidate = ROOT / "models"
    weight = candidate / "bge-small-zh-v1.5" / "model.safetensors"
    if not weight.is_file():
        raise unittest.SkipTest("缺少 bge 模型")
    return candidate


class LatinNameTests(unittest.TestCase):
    def test_latin_names_ignore_case_title_and_possessive(self):
        ensure_scripts_path()
        from router import canonicalize_entity, extract_query_entity, verify_entity_guard

        self.assertEqual(canonicalize_entity("Dr. Elena Brooks's"), "Elena Brooks")
        self.assertEqual(canonicalize_entity("mira chen"), "Mira Chen")
        self.assertEqual(extract_query_entity("What is Mira Chen's cat's name?"), "Mira Chen")
        self.assertEqual(extract_query_entity("where does mira chen live?"), "Mira Chen")
        self.assertEqual(extract_query_entity("What is Dr. Elena Brooks's dog's name?"), "Elena Brooks")
        self.assertEqual(extract_query_entity("What is the name of the dog Elena Brooks keeps?"), "Elena Brooks")
        self.assertTrue(verify_entity_guard("What is elena brooks's dog's name?", ["Dr. Elena Brooks"]))
        self.assertTrue(verify_entity_guard("What is the name of the dog Elena Brooks keeps?", ["Dr. Elena Brooks"]))
        self.assertTrue(verify_entity_guard("What is Mira Chen's bicycle color?", ["Mira Chen"]))
        self.assertFalse(verify_entity_guard("What is Elena Brooks's dog's name?", ["Mira Chen"]))


class RouteGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_scripts_path()
        bind_bge(models_dir())
        cls.records = load_experts(ROOT / "experts", writable=False)
        if len(cls.records) != 5:
            raise unittest.SkipTest("研究专家没有加载全")

    def test_router_api_still_there(self):
        import inspect
        import router

        for name in ("embed", "router_key", "extract_entities_from_key_texts", "extract_query_entity", "verify_entity_guard"):
            self.assertTrue(callable(getattr(router, name)))
            self.assertTrue(inspect.signature(getattr(router, name)))

    def test_legacy_pool_matches_eval_memory(self):
        generic = [json.loads(line) for line in (ROOT / "data" / "generic_questions.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        questions = [item["q"] for item in generic]
        for batch in range(5):
            for line in (ROOT / "data" / f"batch_{batch}.jsonl").read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                fact = json.loads(line)
                questions.append(fact["qa"][0]["q"])
        for question in questions:
            legacy_name, _sim, legacy_fired, _entity = legacy_top1(question, self.records, 0.6)
            decision = route_text(question, self.records, GATE)
            self.assertEqual(decision.fired, legacy_fired, question)
            if legacy_fired:
                self.assertEqual(decision.expert, legacy_name, question)

    def test_delete_expert_4_no_crossfire(self):
        remaining = [record for record in self.records if record.name != "expert_4"]
        fired = 0
        total = 0
        for line in (ROOT / "data" / "batch_4.jsonl").read_text(encoding="utf-8").splitlines():
            fact = json.loads(line)
            for qa in fact["qa"]:
                total += 1
                decision = route_text(qa["q"], remaining, GATE)
                legacy_name, _sim, legacy_fired, _entity = legacy_top1(qa["q"], remaining, 0.6)
                self.assertEqual(decision.fired, legacy_fired, qa["q"])
                if decision.fired:
                    fired += 1
                    self.fail(f"交叉误射 {qa['q']} -> {decision.expert} legacy={legacy_name}")
        self.assertGreater(total, 100)
        self.assertEqual(fired, 0)

    def test_modifier_alias_keeps_guard_open(self):
        from router import extract_query_entity, verify_entity_guard

        from memory_core.store import guard_entity_aliases

        question = "沈星河最喜欢的茶是什么？"
        self.assertEqual(extract_query_entity(question), "沈星河")
        self.assertTrue(verify_entity_guard(question, ["沈星河"]))
        aliases = guard_entity_aliases(["沈星河"], [question, "沈星河的猫的名字是什么？", "沈星河住在哪里？"])
        self.assertEqual(aliases, ["沈星河"])
        self.assertNotIn("沈星河最喜欢", aliases)
        self.assertNotIn("沈星河住在哪里", aliases)
        self.assertTrue(verify_entity_guard("沈星河喜欢喝什么茶？", aliases))
        self.assertTrue(verify_entity_guard("沈星河的猫的名字是什么？", aliases))
        self.assertFalse(verify_entity_guard(question, ["周明远"]))

    def test_explicit_expert_delete_does_not_crossfire(self):
        ensure_scripts_path()
        import torch
        from router import embed

        root = ROOT / ".cache" / "route_guard_case"
        if root.exists():
            shutil.rmtree(root)
        question = "沈星河的猫的名字是什么？"
        key = embed([question, "沈星河的猫的名字是云朵。"])
        entries = []
        for name, entity, batch in (("expert_1000", "沈星河", 1000), ("expert_1001", "周明远", 1001)):
            directory = root / name
            directory.mkdir(parents=True)
            torch.save(key.clone(), directory / "router_key.pt")
            (directory / "key_texts.json").write_text(json.dumps([question], ensure_ascii=False), encoding="utf-8")
            memory = {
                "entities": [entity],
                "display_name": entity,
                "source_conversations": [],
                "facts": [{
                    "statement": f"{entity}的猫的名字是云朵。",
                    "entity": entity,
                    "attr": "猫的名字",
                    "value": "云朵",
                    "qa": [{"q": question if entity == "沈星河" else "周明远的猫的名字是什么？", "a": "云朵"}],
                }],
            }
            (directory / "fact_memory.json").write_text(json.dumps(memory, ensure_ascii=False), encoding="utf-8")
            entries.append({
                "expert": name,
                "batch": batch,
                "n_facts": 1,
                "rank": 32,
                "key_path": str(directory / "router_key.pt"),
            })
        router_path = root / "router.jsonl"
        router_path.write_text("".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in entries), encoding="utf-8")
        both = load_experts(root, writable=True)
        hit = route_text(question, both, GATE)
        self.assertTrue(hit.fired)
        self.assertEqual(hit.expert, "expert_1000")
        self.assertEqual(hit.reason, "entity_first")
        left = [record for record in both if record.name != "expert_1000"]
        missed = route_text(question, left, GATE)
        self.assertFalse(missed.fired, missed)
        general = route_text("水的化学式是什么？", both, GATE)
        self.assertFalse(general.fired, general)
        cmmlu = route_text("下列哪一项属于中国传统节日？A. 春节 B. 万圣节 C. 感恩节 D. 复活节", both, GATE)
        self.assertFalse(cmmlu.fired, cmmlu)
        shutil.rmtree(root)


if __name__ == "__main__":
    unittest.main()

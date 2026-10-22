"""事实语义闸：改写问句要挂上对应事实，没写过的属性回基座，旧专家不被新专家抢走。"""
import json
import shutil
import unittest
from pathlib import Path

from memory_core.e2e_check import GENERAL, NEVER, PARAPHRASE, QUESTIONS
from memory_core.extract import expand_training_fact
from memory_core.fact_span import build_fact_bank, load_fact_bank, save_fact_bank
from memory_core.gate import keep_for_training
from memory_core.paths import ensure_scripts_path
from memory_core.routing import bind_bge, legacy_top1, route_text, route_with_trace
from memory_core.store import guard_entity_aliases, load_experts

ROOT = Path(__file__).resolve().parents[1]
GATE = {"tau": 0.6, "fact_tau": 0.6, "dedup_sim": 0.94}

SHEN = [
    {"entity": "沈星河", "attr": "猫的名字", "value": "云朵", "statement": "沈星河的猫的名字是云朵。", "question": "沈星河的猫的名字是什么？", "answer": "云朵"},
    {"entity": "沈星河", "attr": "住址", "value": "青岚镇", "statement": "沈星河的住址是青岚镇。", "question": "沈星河的住址是什么？", "answer": "青岚镇"},
    {"entity": "沈星河", "attr": "自行车颜色", "value": "朱红色", "statement": "沈星河的自行车颜色是朱红色。", "question": "沈星河的自行车颜色是什么？", "answer": "朱红色"},
    {"entity": "沈星河", "attr": "最喜欢的茶", "value": "桂花乌龙", "statement": "沈星河最喜欢的茶是桂花乌龙。", "question": "沈星河最喜欢的茶是什么？", "answer": "桂花乌龙"},
]


def models_dir() -> Path:
    weight = ROOT / "models" / "bge-small-zh-v1.5" / "model.safetensors"
    if not weight.is_file():
        raise unittest.SkipTest("缺少 bge 模型")
    return ROOT / "models"


class KeepTests(unittest.TestCase):
    def test_skipped_fact_cannot_be_selected_back(self):
        self.assertFalse(keep_for_training({"gate": "skip_known", "selected": True, "entity": "沈星河", "value": "古筝"}))
        self.assertFalse(keep_for_training({"gate": "skip_duplicate", "selected": True}))
        self.assertTrue(keep_for_training({"gate": "write", "selected": True}))
        self.assertFalse(keep_for_training({"gate": "write", "selected": False}))
        self.assertTrue(keep_for_training({"entity": "沈星河", "value": "云朵"}))


class FactSpanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_scripts_path()
        bind_bge(models_dir())
        cls.expanded = [expand_training_fact(fact) for fact in SHEN]
        trained = {qa["q"] for fact in cls.expanded for qa in fact["qa"]}
        cls.trained = trained
        cls.bank = build_fact_bank(cls.expanded)

    def test_held_out_questions_are_not_training_copies(self):
        for question, _gold in PARAPHRASE:
            self.assertNotIn(question, self.trained, question)
        for question in NEVER:
            self.assertNotIn(question, self.trained, question)

    def test_primary_and_paraphrase_match_the_attribute(self):
        gold_attr = {"云朵": "猫的名字", "青岚镇": "住址", "朱红色": "自行车颜色", "桂花乌龙": "最喜欢的茶"}
        for question, gold in QUESTIONS + PARAPHRASE:
            ok, score, got = self.bank.allows(question)
            self.assertTrue(ok, f"{question} score={score:.3f}")
            self.assertEqual(got, gold_attr[gold], question)

    def test_never_written_attributes_abstain(self):
        missed = []
        for question in NEVER:
            ok, score, attr = self.bank.allows(question)
            if ok:
                missed.append(f"{question} -> {attr} {score:.3f}")
        rate = 1 - len(missed) / len(NEVER)
        print("ABSTAIN", f"{len(NEVER) - len(missed)}/{len(NEVER)}", missed, flush=True)
        self.assertGreaterEqual(rate, 0.90, missed)
        self.assertGreaterEqual(len(NEVER), 10)

    def test_hometown_paraphrase_does_not_match_another_fact(self):
        facts = [
            expand_training_fact({
                "entity": "林晚舟", "attr": "老家", "value": "青石县",
                "statement": "林晚舟的老家是青石县。", "question": "林晚舟的老家是什么？", "answer": "青石县",
            }),
            expand_training_fact({
                "entity": "林晚舟", "attr": "早餐", "value": "豆包",
                "statement": "林晚舟的早餐是豆包。", "question": "林晚舟的早餐是什么？", "answer": "豆包",
            }),
        ]
        bank = build_fact_bank(facts)
        ok, score, attr = bank.allows("林晚舟老家在哪儿？")
        self.assertTrue(ok, score)
        self.assertEqual(attr, "老家")
        ok, _score, attr = bank.allows("林晚舟早餐吃什么？")
        self.assertTrue(ok)
        self.assertEqual(attr, "早餐")

    def test_skipped_fact_is_not_routable(self):
        kept = []
        for fact in (
            {"entity": "沈星河", "attr": "猫的名字", "value": "云朵", "statement": "沈星河的猫的名字是云朵。", "question": "沈星河的猫的名字是什么？", "answer": "云朵", "gate": "write", "selected": True},
            {"entity": "沈星河", "attr": "乐器", "value": "古筝", "statement": "沈星河的乐器是古筝。", "question": "沈星河的乐器是什么？", "answer": "古筝", "gate": "skip_known", "selected": True},
        ):
            if keep_for_training(fact):
                kept.append(expand_training_fact(fact))
        self.assertEqual(len(kept), 1)
        bank = build_fact_bank(kept)
        ok, _score, _attr = bank.allows("沈星河会弹古筝吗？")
        self.assertFalse(ok)
        ok, _score, _attr = bank.allows("沈星河的乐器是什么？")
        self.assertFalse(ok)
        ok, _score, attr = bank.allows("沈星河的猫的名字是什么？")
        self.assertTrue(ok)
        self.assertEqual(attr, "猫的名字")

    def test_save_roundtrip(self):
        root = ROOT / ".cache" / "fact_span_roundtrip"
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True)
        path = root / "fact_spans.pt"
        save_fact_bank(path, self.bank)
        loaded = load_fact_bank(path, self.expanded)
        self.assertIsNotNone(loaded)
        ok, _score, attr = loaded.allows("沈星河家的猫咪叫啥？")
        self.assertTrue(ok)
        self.assertEqual(attr, "猫的名字")
        shutil.rmtree(root)

    def _materialize(self, root: Path, facts: list[dict], key_texts: list[str]) -> None:
        import torch
        from router import embed

        expanded = [expand_training_fact(fact) for fact in facts]
        directory = root / "expert_1000"
        directory.mkdir(parents=True)
        texts = list(key_texts)
        torch.save(embed(texts), directory / "router_key.pt")
        (directory / "key_texts.json").write_text(json.dumps(texts, ensure_ascii=False), encoding="utf-8")
        entities = []
        for fact in expanded:
            if fact["entity"] not in entities:
                entities.append(fact["entity"])
        alias_texts = list(texts)
        for fact in expanded:
            alias_texts.append(fact["statement"])
            alias_texts.extend(qa["q"] for qa in fact["qa"])
        entities = guard_entity_aliases(entities, alias_texts)
        memory = {"entities": entities, "display_name": "沈星河", "source_conversations": [], "facts": expanded}
        (directory / "fact_memory.json").write_text(json.dumps(memory, ensure_ascii=False), encoding="utf-8")
        (root / "router.jsonl").write_text(json.dumps({
            "expert": "expert_1000", "batch": 1000, "n_facts": len(expanded), "rank": 32,
            "key_path": "expert_1000/router_key.pt", "display_name": "沈星河",
        }, ensure_ascii=False) + "\n", encoding="utf-8")

    def test_route_text_abstains_on_unwritten_attribute(self):
        root = ROOT / ".cache" / "fact_span_route"
        if root.exists():
            shutil.rmtree(root)
        self._materialize(root, SHEN, [fact["question"] for fact in SHEN])
        records = load_experts(root, writable=True)
        hit = route_text("沈星河的猫的名字是什么？", records, GATE)
        self.assertTrue(hit.fired, hit)
        self.assertEqual(hit.expert, "expert_1000")
        self.assertEqual(hit.reason, "entity_first")
        dog = route_text("沈星河的狗叫什么？", records, GATE)
        self.assertFalse(dog.fired, dog)
        self.assertEqual(dog.reason, "fact_gate")
        car = route_text("沈星河的汽车颜色是什么？", records, GATE)
        self.assertFalse(car.fired, car)
        birthday = route_text("沈星河的生日是什么时候？", records, GATE)
        self.assertFalse(birthday.fired, birthday)
        bike = route_text("沈星河那辆自行车是什么颜色？", records, GATE)
        self.assertTrue(bike.fired, bike)
        self.assertEqual(bike.reason, "entity_first")
        abstained = 0
        for question in NEVER:
            decision = route_text(question, records, GATE)
            abstained += int(not decision.fired)
        self.assertGreaterEqual(abstained / len(NEVER), 0.90)
        for question in GENERAL:
            decision = route_text(question, records, GATE)
            self.assertFalse(decision.fired, question)
        shutil.rmtree(root)

    def test_recall_trace_matches_route_and_names_the_fact(self):
        root = ROOT / ".cache" / "fact_span_trace"
        if root.exists():
            shutil.rmtree(root)
        self._materialize(root, SHEN, [fact["question"] for fact in SHEN])
        memory_path = root / "expert_1000" / "fact_memory.json"
        memory = json.loads(memory_path.read_text(encoding="utf-8"))
        memory["facts"][0]["id"] = "old-cat"
        memory["facts"][0]["superseded"] = True
        memory["facts"][0]["superseded_by"] = "new-cat"
        replacement = expand_training_fact({
            "entity": "沈星河", "attr": "猫的名字", "value": "暮雪",
            "statement": "沈星河的猫的名字是暮雪。", "question": "沈星河的猫的名字是什么？", "answer": "暮雪",
        })
        replacement["id"] = "new-cat"
        memory["facts"].append(replacement)
        memory_path.write_text(json.dumps(memory, ensure_ascii=False), encoding="utf-8")
        records = load_experts(root, writable=True)
        samples = [
            "沈星河的猫的名字是什么？",
            "沈星河的生日是什么时候？",
            "水的化学式是什么？",
        ]
        for question in samples:
            decision = route_text(question, records, GATE)
            traced, trace = route_with_trace(question, records, GATE)
            self.assertEqual(decision.public_dict(), traced.public_dict(), question)
            self.assertEqual(trace["mounted"], decision.fired, question)
            self.assertEqual(trace["thresholds"]["router_tau"], 0.6)
            self.assertGreaterEqual(trace["thresholds"]["fact_tau"], 0.622)
            self.assertEqual(len(trace["experts"]), 1)
            self.assertIsInstance(trace["experts"][0]["sim"], float)
        _decision, hit = route_with_trace(samples[0], records, GATE)
        self.assertTrue(hit["mounted"], hit)
        matched_ids = {item["fact_id"] for item in hit["matched_facts"]}
        self.assertIn("new-cat", matched_ids)
        self.assertNotIn("old-cat", matched_ids)
        self.assertTrue(all(item["value"] != "云朵" for item in hit["fact_gate"]["facts"]))
        self.assertTrue(any(item["fact_id"] == "new-cat" and item["passed"] for item in hit["fact_gate"]["facts"]))
        _decision, miss = route_with_trace(samples[1], records, GATE)
        self.assertFalse(miss["mounted"])
        self.assertEqual(miss["matched_facts"], [])
        self.assertEqual(miss["reason"], "fact_gate")
        self.assertGreater(len(miss["fact_gate"]["facts"]), 1)
        self.assertTrue(all(not item["passed"] for item in miss["fact_gate"]["facts"]))
        _decision, base = route_with_trace(samples[2], records, GATE)
        self.assertFalse(base["mounted"])
        self.assertEqual(base["matched_facts"], [])
        shutil.rmtree(root)

    def test_existing_experts_stay_250_with_new_expert(self):
        records = load_experts(ROOT / "experts", writable=False)
        if len(records) != 5:
            raise unittest.SkipTest("研究专家没有加载全")
        root = ROOT / ".cache" / "fact_span_with_existing"
        if root.exists():
            shutil.rmtree(root)
        self._materialize(root, SHEN, [fact["statement"] for fact in SHEN] + [fact["question"] for fact in SHEN])
        mixed = records + load_experts(root, writable=True)
        questions = []
        for batch in range(5):
            for line in (ROOT / "data" / f"batch_{batch}.jsonl").read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                fact = json.loads(line)
                if not fact.get("qa") or fact.get("_common"):
                    continue
                questions.append(fact["qa"][0]["q"])
        self.assertEqual(len(questions), 250)
        for question in questions:
            legacy_name, _sim, legacy_fired, _entity = legacy_top1(question, records, 0.6)
            decision = route_text(question, mixed, GATE)
            self.assertEqual(decision.fired, legacy_fired, question)
            if legacy_fired:
                self.assertEqual(decision.expert, legacy_name, question)
                self.assertNotEqual(decision.expert, "expert_1000")
        generic = [json.loads(line) for line in (ROOT / "data" / "generic_questions.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        fired = 0
        for item in generic:
            decision = route_text(item["q"], mixed, GATE)
            legacy_name, _sim, legacy_fired, _entity = legacy_top1(item["q"], records, 0.6)
            self.assertEqual(decision.fired, legacy_fired, item["q"])
            if decision.fired and decision.expert == "expert_1000":
                fired += 1
        self.assertEqual(fired, 0)
        shutil.rmtree(root)

    def test_stolen_router_key_does_not_take_a_company_question(self):
        records = load_experts(ROOT / "experts", writable=False)
        if len(records) != 5:
            raise unittest.SkipTest("研究专家没有加载全")
        question = None
        for line in (ROOT / "data" / "batch_0.jsonl").read_text(encoding="utf-8").splitlines():
            fact = json.loads(line)
            if fact.get("qa") and not fact.get("_common"):
                question = fact["qa"][0]["q"]
                break
        self.assertIsNotNone(question)
        root = ROOT / ".cache" / "fact_span_stolen"
        if root.exists():
            shutil.rmtree(root)
        self._materialize(root, SHEN, [question])
        mixed = records + load_experts(root, writable=True)
        legacy_name, _sim, legacy_fired, _entity = legacy_top1(question, records, 0.6)
        decision = route_text(question, mixed, GATE)
        self.assertEqual(decision.fired, legacy_fired)
        self.assertNotEqual(decision.expert, "expert_1000")
        if legacy_fired:
            self.assertEqual(decision.expert, legacy_name)
        shutil.rmtree(root)


if __name__ == "__main__":
    unittest.main()

import json
import unittest
from pathlib import Path

from memory_core.extract import entailed, expand_training_fact, pattern_extract
from memory_core.prompts import with_brief

TURNS = [
    "沈星河的猫的名字是云朵。",
    "沈星河的住址是青岚镇。",
    "沈星河的自行车颜色是朱红色。",
    "沈星河最喜欢的茶是桂花乌龙。",
]


class ExtractTests(unittest.TestCase):
    def test_statements_not_fixed_categories(self):
        facts = pattern_extract("\n".join(TURNS))
        values = {fact["value"] for fact in facts}
        self.assertEqual(values, {"云朵", "青岚镇", "朱红色", "桂花乌龙"})
        attrs = {fact["attr"] for fact in facts}
        self.assertTrue(attrs.isdisjoint({"CEO", "成立年份", "总部城市", "旗舰产品"}))
        tea = next(fact for fact in facts if fact["value"] == "桂花乌龙")
        self.assertEqual(tea["entity"], "沈星河")
        self.assertEqual(tea["attr"], "最喜欢的茶")
        self.assertEqual(tea["statement"], "沈星河最喜欢的茶是桂花乌龙。")
        self.assertEqual(tea["question"], "沈星河最喜欢的茶是什么？")
        for fact in facts:
            self.assertTrue(entailed(fact, "\n".join(TURNS)))
            trained = expand_training_fact(fact)
            self.assertGreaterEqual(len(trained["qa"]), 4)
            self.assertTrue(all(item["a"] == fact["value"] for item in trained["qa"]))

    def test_questions_are_not_facts(self):
        facts = pattern_extract("沈星河的猫的名字是什么？水的化学式是什么？")
        self.assertEqual(facts, [])

    def test_brief_suffix_keeps_chinese(self):
        self.assertEqual(with_brief("沈星河的猫的名字是什么？"), "沈星河的猫的名字是什么？ 请简短回答。")
        self.assertEqual(with_brief("What is Mira Chen's cat's name?"), "What is Mira Chen's cat's name? Answer briefly.")

    def test_english_statements(self):
        text = "\n".join([
            "Mira Chen's cat's name is Snow.",
            "Mira Chen lives in Qinglan.",
            "Mira Chen's bicycle color is vermilion.",
            "Mira Chen's favorite tea is osmanthus oolong.",
            "What is Mira Chen's cat's name?",
        ])
        facts = pattern_extract(text)
        values = {fact["value"] for fact in facts}
        self.assertEqual(values, {"Snow", "Qinglan", "vermilion", "osmanthus oolong"})
        cat = next(fact for fact in facts if fact["value"] == "Snow")
        self.assertEqual(cat["entity"], "Mira Chen")
        self.assertEqual(cat["attr"], "cat's name")
        self.assertTrue(cat["question"].endswith("?"))
        home = next(fact for fact in facts if fact["value"] == "Qinglan")
        self.assertEqual(home["attr"], "where they live")
        self.assertIn("Where does Mira Chen live?", home["question"])
        cello = pattern_extract("Mira Chen's instrument is the cello.")
        self.assertEqual(cello[0]["value"], "cello")
        self.assertEqual(pattern_extract("沈星河的乐器是古筝。")[0]["value"], "古筝")
        for fact in facts:
            self.assertTrue(entailed(fact, text))
            trained = expand_training_fact(fact)
            self.assertGreaterEqual(len(trained["qa"]), 4)
            self.assertTrue(all(item["a"] == fact["value"] for item in trained["qa"]))
            self.assertTrue(any(item["q"].startswith("What") or item["q"].startswith("Where") for item in trained["qa"]))

    def test_hallucinated_value_dropped(self):
        self.assertFalse(entailed({"entity": "沈星河", "value": "不存在的取值"}, "沈星河的猫的名字是云朵。"))


if __name__ == "__main__":
    unittest.main()

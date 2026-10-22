import json
import unittest
from pathlib import Path

from memory_core.extract import entailed, expand_training_fact, pattern_extract

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

    def test_hallucinated_value_dropped(self):
        self.assertFalse(entailed({"entity": "沈星河", "value": "不存在的取值"}, "沈星河的猫的名字是云朵。"))


if __name__ == "__main__":
    unittest.main()

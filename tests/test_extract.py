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

    def test_property_stays_on_the_attribute(self):
        bike = pattern_extract("林晚舟的自行车是朱红色的")[0]
        self.assertEqual(bike["attr"], "自行车颜色")
        self.assertEqual(bike["value"], "朱红色的")
        dog = pattern_extract("林晚舟的狗叫豆包")[0]
        self.assertEqual(dog["attr"], "狗的名字")
        self.assertEqual(dog["value"], "豆包")
        car = pattern_extract("Marcus Whitfield's car is blue.")[0]
        self.assertEqual(car["attr"], "car color")
        self.assertEqual(car["value"], "blue")

    def test_named_and_called_keep_the_name_attribute(self):
        named = pattern_extract("Elena Brooks's dog is named Juniper.")
        self.assertEqual(named[0]["attr"], "dog's name")
        self.assertEqual(named[0]["value"], "Juniper")
        self.assertEqual(named[0]["question"], "What is Elena Brooks's dog's name?")
        called = pattern_extract("Mira Chen's cat is called Snow.")
        self.assertEqual(called[0]["attr"], "cat's name")
        self.assertEqual(called[0]["value"], "Snow")
        self.assertIn("cat's name", called[0]["question"])
        already = pattern_extract("Elena Brooks's dog's name is Juniper.")
        self.assertEqual(already[0]["attr"], "dog's name")
        self.assertEqual(already[0]["value"], "Juniper")

    def test_my_pet_diminutive_is_the_users_cat(self):
        fact = pattern_extract("我的猫猫叫咪咪")[0]
        self.assertEqual(fact["entity"], "我")
        self.assertEqual(fact["attr"], "猫的名字")
        self.assertEqual(fact["value"], "咪咪")
        dog = pattern_extract("我的狗狗叫豆包")[0]
        self.assertEqual(dog["entity"], "我")
        self.assertEqual(dog["attr"], "狗的名字")
        mother = pattern_extract("我的妈妈叫兰兰")[0]
        self.assertEqual(mother["entity"], "我")
        self.assertEqual(mother["attr"], "妈妈的名字")
        self.assertEqual(mother["value"], "兰兰")

    def test_hallucinated_value_dropped(self):
        self.assertFalse(entailed({"entity": "沈星河", "value": "不存在的取值"}, "沈星河的猫的名字是云朵。"))


if __name__ == "__main__":
    unittest.main()

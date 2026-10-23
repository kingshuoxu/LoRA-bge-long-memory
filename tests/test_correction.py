"""纠正对的是哪条事实、新取值是什么。不训练。"""
from __future__ import annotations

import unittest
from pathlib import Path

import torch

from memory_core.extract import expand_training_fact
from memory_core.fact_span import build_fact_bank
from memory_core.paths import default_models_dir
from memory_core.store import ExpertRecord


def _models():
    path = default_models_dir()
    if not (path / "bge-small-zh-v1.5").is_dir():
        raise unittest.SkipTest("没有 bge")
    return path


def _record():
    raws = [
        {"entity": "沈星河", "attr": "猫的名字", "value": "云朵", "statement": "沈星河的猫的名字是云朵。", "question": "沈星河的猫的名字是什么？", "answer": "云朵"},
        {"entity": "沈星河", "attr": "住址", "value": "青岚镇", "statement": "沈星河的住址是青岚镇。", "question": "沈星河的住址是什么？", "answer": "青岚镇"},
        {"entity": "沈星河", "attr": "自行车颜色", "value": "朱红色", "statement": "沈星河的自行车颜色是朱红色。", "question": "沈星河的自行车颜色是什么？", "answer": "朱红色"},
        {"entity": "沈星河", "attr": "最喜欢的茶", "value": "桂花乌龙", "statement": "沈星河最喜欢的茶是桂花乌龙。", "question": "沈星河最喜欢的茶是什么？", "answer": "桂花乌龙"},
    ]
    facts = []
    for index, raw in enumerate(raws, start=1):
        item = expand_training_fact(raw)
        item["id"] = f"f{index}"
        facts.append(item)
    return ExpertRecord(
        name="expert_1000",
        directory=Path("."),
        experts_dir=Path("."),
        writable=True,
        key_path=Path("."),
        key=torch.zeros(1, 8),
        entities=["沈星河"],
        explicit=True,
        display_name="沈星河",
        n_facts=4,
        rank=32,
        batch=1000,
        fact_memory={"facts": facts},
    )


class CorrectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from memory_core.routing import bind_bge

        bind_bge(_models())

    def test_identify_without_keyword_lists(self):
        from memory_core.correct import propose_from_records

        record = _record()
        expect = {
            "沈星河的猫的名字不是云朵，正确的是暮雪。": "暮雪",
            "记错了，沈星河的猫叫暮雪。": "暮雪",
            "沈星河的住址不是青岚镇，是星港。": "星港",
            "沈星河最喜欢的茶其实是茉莉花茶。": "茉莉花茶",
            "暮雪才是沈星河的猫的名字，不是云朵。": "暮雪",
            "沈星河的猫的名字是什么？": None,
            "沈星河住哪儿？": None,
            "沈星河养的那只猫叫什么名字？": None,
            "沈星河家的猫咪叫啥？": None,
            "沈星河那辆自行车是什么颜色？": None,
            "沈星河最爱喝的茶是哪种？": None,
            "沈星河喜欢喝什么茶？": None,
            "沈星河养的狗叫什么名字？": None,
            "沈星河的生日是什么时候？": None,
            "沈星河的电话是多少？": None,
            "沈星河的母亲是谁？": None,
            "沈星河多大了？": None,
            "沈星河喜欢吃什么？": None,
            "水的化学式是什么？": None,
            "沈星河的猫叫什么？": None,
            "林晚舟的猫叫什么？": None,
            "沈星河的狗是不是叫可乐？": None,
            "沈星河最喜欢的咖啡是什么？": None,
            "沈星河的猫是不是叫云朵？": None,
            "沈星河的自行车是不是朱红色？": None,
            "沈星河是不是住在青岚镇？": None,
            "沈星河最喜欢的茶是不是桂花乌龙？": None,
            "沈星河家住哪？": None,
            "沈星河的单车是什么颜色？": None,
            "沈星河骑的那辆车是什么颜色？": None,
            "沈星河喜欢喝什么茶叶？": None,
            "沈星河最中意的茶是什么？": None,
            "沈星河会弹古筝吗？": None,
            "沈星河的汽车是什么颜色？": None,
            "沈星河养的狗是不是叫可乐？": None,
            "沈星河的茶是咖啡吗？": None,
            "你知道沈星河住在哪里吗？": None,
            "沈星河的猫呢？": None,
            "请问林晚舟的猫叫什么名字？": None,
            "沈星河有没有养狗？": None,
        }
        for text, gold in expect.items():
            got = propose_from_records(text, [record])
            value = None if got is None else got["new_value"]
            self.assertEqual(value, gold, text)

    def test_english_correction_is_embedding_only(self):
        from memory_core.correct import propose_from_records

        raws = [
            {"entity": "Mira Chen", "attr": "cat's name", "value": "Snow", "statement": "Mira Chen's cat's name is Snow.", "question": "What is Mira Chen's cat's name?", "answer": "Snow"},
            {"entity": "Mira Chen", "attr": "where they live", "value": "Qinglan", "statement": "Mira Chen lives in Qinglan.", "question": "Where does Mira Chen live?", "answer": "Qinglan"},
            {"entity": "Elena Brooks", "attr": "dog's name", "value": "Pepper", "statement": "Elena Brooks's dog's name is Pepper.", "question": "What is Elena Brooks's dog's name?", "answer": "Pepper"},
        ]
        facts = []
        for index, raw in enumerate(raws, start=1):
            item = expand_training_fact(raw)
            item["id"] = f"e{index}"
            facts.append(item)
        record = _record()
        record.entities = ["Mira Chen", "Elena Brooks"]
        record.display_name = "Mira Chen"
        record.fact_memory = {"facts": facts}
        expect = {
            "Mira Chen's cat's name is not Snow, it is Ash.": "Ash",
            "Mira Chen lives in Starport, not Qinglan.": "Starport",
            "What is Mira Chen's cat's name?": None,
            "Where does Mira Chen live?": None,
            "What is Elena Brooks's dog's name?": None,
            "Elena Brooks's dog's name is not Pepper, it is Juniper.": "Juniper",
            "Is Elena Brooks's dog called Pepper?": None,
            "Elena Brooks lives in Boston, isn't she?": None,
            "Mira Chen's cat's name is Snow, right?": None,
            "What breed of dog does Elena Brooks keep?": None,
            "Is Mira Chen's cat called Snow?": None,
            "Does Mira Chen live in Qinglan?": None,
            "Isn't Mira Chen's cat called Ash?": None,
            "Mira Chen lives in Qinglan, doesn't she?": None,
            "Snow is the cat's name, isn't it?": None,
            "The dog is called Pepper, right?": None,
            "What colour is Mira Chen's bicycle?": None,
            "Where is Mira Chen's home?": None,
            "What is the name of the dog Elena Brooks keeps?": None,
            "Can you tell me Mira Chen's cat's name?": None,
            "Did Mira Chen move to Boston?": None,
            "How old is Mira Chen?": None,
            "What is Mira Chen's phone number?": None,
            "Who is Elena Brooks's sister?": None,
            "What color is Elena Brooks's car?": None,
            "Is Boston where Mira Chen lives?": None,
            "Mira Chen's cat is Snow, isn't it?": None,
            "Would Elena's dog be named Pepper?": None,
            "What's Mira's favorite coffee?": None,
            "Elena Brooks's dog isn't Juniper, is it?": None,
            "Pepper, right?": None,
            "Qinglan is not where she lives, is it?": None,
            "Has Elena Brooks got a dog named Pepper?": None,
            "Should I call Mira Chen's cat Snow?": None,
        }
        for text, gold in expect.items():
            got = propose_from_records(text, [record])
            value = None if got is None else got["new_value"]
            self.assertEqual(value, gold, text)

    def test_reissue_updates_every_question(self):
        from memory_core.correct import reissue_training_fact

        fact = expand_training_fact({
            "entity": "Mira Chen",
            "attr": "cat",
            "value": "Max",
            "statement": "Mira Chen's cat is named Max.",
            "question": "What is Mira Chen's cat?",
            "answer": "Max",
        })
        fact["gate_questions"] = ["What is Mira Chen's cat called?"]
        fresh = reissue_training_fact(fact, "Juniper")
        blob = " ".join(qa["q"] + " " + qa["a"] for qa in fresh["qa"])
        self.assertNotIn("Max", blob)
        self.assertTrue(all(qa["a"] == "Juniper" for qa in fresh["qa"]))
        self.assertIn("What is Mira Chen's cat's name?", [qa["q"] for qa in fresh["qa"]])
        self.assertIn("What is Mira Chen's cat?", [qa["q"] for qa in fresh["qa"]])
        self.assertEqual(fresh["gate_questions"], ["What is Mira Chen's cat called?"])
        self.assertEqual(fresh["attr"], "cat's name")

    def test_titles_break_on_words(self):
        from memory_core.service import _conversation_title

        title = _conversation_title("Please remember that Mira Chen's bicycle is vermilion today")
        self.assertNotIn("vermil", title)
        self.assertFalse(title.endswith(" "))
        self.assertEqual(title, title.rstrip())
        self.assertEqual(_conversation_title("Short title"), "Short title")
        chinese = _conversation_title("沈星河的自行车颜色是朱红色，请记住这件事")
        self.assertLessEqual(len(chinese), 16)

    def test_panel_value_and_superseded_bank(self):
        from memory_core.correct import propose_from_records

        record = _record()
        got = propose_from_records("暮雪", [record], fact_id="f1", new_value="暮雪")
        self.assertEqual(got["new_statement"], "沈星河的猫的名字是暮雪。")
        facts = list(record.fact_memory["facts"])
        facts[0] = dict(facts[0])
        facts[0]["superseded"] = True
        bank = build_fact_bank(facts)
        self.assertNotIn("猫的名字", bank.attrs)
        self.assertIn("住址", bank.attrs)


if __name__ == "__main__":
    unittest.main()

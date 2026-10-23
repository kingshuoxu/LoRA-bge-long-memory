"""开放问句和没写过的属性都不交给基座编。"""
import unittest

from memory_core.e2e_check import abstain_ok
from memory_core.extract import pattern_extract
from memory_core.fact_span import entity_mentioned
from memory_core.grounding import (
    acknowledge_statement,
    contradicting_facts,
    ground_if_unknown,
    missing_topic,
    open_entity_question,
    overview_if_open,
    overview_reply,
)
from memory_core.routing import _entity_hit, _owner


class _Expert:
    def __init__(self, name, facts):
        self.name = name
        self.display_name = name
        self.entities = [facts[0]["entity"]] if facts else []
        self.fact_memory = {"facts": facts}
        self.explicit = True


ZORE = [{
    "id": "founded",
    "entity": "佐雷公司",
    "attr": "成立年份",
    "value": "1979年",
    "statement": "佐雷公司成立于1979年。",
}]


class GroundingTests(unittest.TestCase):
    def test_open_company_question_uses_only_the_stored_year(self):
        questions = [
            "告诉我佐雷公司相关信息",
            "介绍一下佐雷公司",
            "佐雷公司的情况",
            "关于佐雷公司",
        ]
        for question in questions:
            self.assertTrue(open_entity_question(question, "佐雷公司"), question)
        self.assertFalse(open_entity_question("佐雷公司的总部在哪里？", "佐雷公司"))
        self.assertFalse(open_entity_question("佐雷公司的成立年份是哪一年？", "佐雷公司"))
        reply = overview_reply("佐雷公司", ZORE)
        self.assertIn("1979", reply)
        self.assertIn("不在记忆里", reply)
        self.assertNotIn("1998", reply)
        self.assertNotIn("圣迭戈", reply)
        self.assertEqual(contradicting_facts(reply, ZORE), [])
        expert = _Expert("zore", ZORE)
        opened = overview_if_open("告诉我佐雷公司相关信息", [expert])
        self.assertIsNotNone(opened)
        answer, owner, facts = opened
        self.assertEqual(owner.name, "zore")
        self.assertEqual(facts, ZORE)
        self.assertIn("1979", answer)
        self.assertNotIn("1998", answer)
        self.assertNotIn("圣迭戈", answer)

    def test_unknown_attribute_lists_what_is_known(self):
        question = "佐雷公司的总部在哪里？"
        self.assertEqual(missing_topic(question, "佐雷公司", ZORE), "总部")
        reply = overview_reply("佐雷公司", ZORE, missing="总部")
        self.assertIn("1979", reply)
        self.assertIn("总部不在记忆里", reply)
        self.assertNotIn("1998", reply)
        self.assertNotIn("圣迭戈", reply)
        self.assertEqual(contradicting_facts(reply, ZORE, topic="总部"), [])
        closed = ground_if_unknown(question, [_Expert("zore", ZORE)])
        self.assertIsNotNone(closed)
        self.assertIn("1979", closed[0])
        self.assertNotIn("圣迭戈", closed[0])

    def test_cat_statement_is_acknowledged_as_the_users(self):
        fact = pattern_extract("我的猫猫叫咪咪")[0]
        self.assertEqual(acknowledge_statement(fact), "好，你的猫叫咪咪。")
        self.assertNotEqual(acknowledge_statement(fact), "咪咪")

    def test_self_mention_does_not_match_tell_me(self):
        self.assertFalse(entity_mentioned("我", "告诉我佐雷公司相关信息"))
        self.assertFalse(entity_mentioned("我", "我们明天出发"))
        self.assertTrue(entity_mentioned("我", "我的猫叫什么"))
        self.assertEqual(_entity_hit("我", "告诉我佐雷公司相关信息"), 0)
        self.assertEqual(_entity_hit("我", "我的猫叫什么"), 1)
        owner = _owner("我的猫叫什么", [_Expert("me", [{
            "entity": "我", "attr": "猫的名字", "value": "咪咪",
        }])])
        self.assertIsNotNone(owner)
        self.assertEqual(owner.name, "me")
        self.assertIsNone(_owner("告诉我佐雷公司相关信息", [_Expert("me", [{
            "entity": "我", "attr": "猫的名字", "value": "咪咪",
        }])]))

    def test_english_open_question_and_unknown_attribute(self):
        facts = [
            {"entity": "Marcus Whitfield", "attr": "dog's name", "value": "Biscuit"},
            {"entity": "Marcus Whitfield", "attr": "where they live", "value": "Bristol"},
        ]
        for question in (
            "Tell me about Marcus Whitfield",
            "What do you know about Marcus Whitfield?",
            "What can you tell me about Marcus Whitfield?",
        ):
            self.assertTrue(open_entity_question(question, "Marcus Whitfield"), question)
        self.assertFalse(open_entity_question("What is Marcus Whitfield's phone number?", "Marcus Whitfield"))
        reply = overview_reply("Marcus Whitfield", facts)
        self.assertIn("Biscuit", reply)
        self.assertIn("Bristol", reply)
        self.assertIn("not in memory", reply)
        self.assertEqual(contradicting_facts(reply, facts), [])
        phone = "What is Marcus Whitfield's phone number?"
        self.assertEqual(missing_topic(phone, "Marcus Whitfield", facts), "phone number")
        grounded = overview_reply("Marcus Whitfield", facts, missing="phone number")
        self.assertIn("Biscuit", grounded)
        self.assertIn("phone number is not in memory", grounded)
        self.assertNotIn("San Diego", grounded)
        self.assertEqual(contradicting_facts(grounded, facts, topic="phone number"), [])
        red = [{"entity": "Rosa Bennett", "attr": "car color", "value": "red"}]
        red_reply = overview_reply("Rosa Bennett", red)
        self.assertIn("red", red_reply)
        self.assertEqual(contradicting_facts(red_reply, red), [])

    def test_price_does_not_deny_a_stored_object(self):
        facts = [{"entity": "林晚舟", "attr": "自行车颜色", "value": "朱红色的"}]
        question = "林晚舟的自行车贵不贵？"
        self.assertFalse(open_entity_question(question, "林晚舟"))
        self.assertEqual(missing_topic(question, "林晚舟", facts), "价格")
        reply = overview_reply("林晚舟", facts, missing="价格")
        self.assertIn("朱红色的", reply)
        self.assertIn("价格不在记忆里", reply)
        self.assertNotIn("自行车不在记忆里", reply)

    def test_grounded_unknown_attribute_counts_as_abstain(self):
        answer = "关于沈星河，记住的是：猫的名字是云朵。狗不在记忆里。"
        self.assertTrue(abstain_ok(
            {"fired": True, "expert": "expert_1000", "reason": "entity_grounded"},
            answer,
            "expert_1000",
        ))
        self.assertFalse(abstain_ok(
            {"fired": True, "expert": "expert_1000", "reason": "entity_first"},
            "云朵",
            "expert_1000",
        ))
        self.assertTrue(abstain_ok(
            {"fired": False, "expert": "expert_1000", "reason": "fact_gate"},
            "不知道",
            "expert_1000",
        ))


if __name__ == "__main__":
    unittest.main()

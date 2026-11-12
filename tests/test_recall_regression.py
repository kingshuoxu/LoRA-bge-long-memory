"""自己的回忆集。答对的题数不能掉到上一档以下。

这不是逐句补丁。每条题都对着已经记下的边：最后一跳的属性和问句一致才算答对。
"""
import unittest

from memory_core.fact_reader import answer_stated_question, read_memory
from memory_core.unseen_personas import build
from memory_core.world_facts import world_reply

# 这组题当前答对 32。少一题就失败，避免再把已经答对的书上事实收成弃权。
BASELINE = 32

BOOK = [
    {"entity": "白鹭塔", "statement": "柯岚在雾港守护的第一座灯塔名叫白鹭塔，建于1873年，塔高四十二米。", "value": "白鹭塔"},
    {"entity": "星砂盐", "statement": "雾港的特产是一种蓝色海盐，名叫星砂盐，每年霜降那天开始晾晒。", "value": "星砂盐"},
    {"entity": "阿哨", "statement": "柯岚的女儿柯小满养了一只三条腿的海鸥，名叫阿哨。", "value": "阿哨"},
    {"entity": "诺丁", "statement": "1931年白鹭塔的灯改用电灯，透镜由瑞典工匠诺丁打磨，一共有十六面。", "value": "诺丁"},
]


def _text(question: str, facts: list[dict]) -> str:
    hit = read_memory(question, facts, None) or {}
    return hit.get("text") or ""


class RecallRegressionTests(unittest.TestCase):
    def test_correct_answers_do_not_drop(self):
        spec = build()
        persona = [
            {"entity": convo["title"], "statement": sentence, "value": sentence}
            for convo in spec["zh"]
            for sentence in convo["sentences"]
        ]
        correct = 0
        wrong = []
        for question, gold in spec["zh_recall"]:
            answer = _text(question, persona)
            if gold in answer:
                correct += 1
            else:
                wrong.append((question, gold, answer))
        book_hits = [
            ("白鹭塔建于哪一年？", "1873"),
            ("白鹭塔有多高？", "四十二"),
            ("柯小满的父亲是谁？", "柯岚"),
            ("柯岚的女儿叫什么？", "柯小满"),
            ("阿哨是谁养的？", "柯小满"),
            ("柯岚女儿养的海鸥有几条腿？", "三"),
            ("星砂盐是什么颜色？", "蓝色"),
            ("瑞典工匠叫啥名？", "诺丁"),
            ("诺丁是哪国人？", "瑞典"),
            ("雾港的蓝色海盐每年哪天开始晒？", "霜降"),
            ("守塔人叫什么？", "柯岚"),
            ("江衡的猫叫小黑。小黑的主人是谁？", "江衡"),
        ]
        extra = BOOK + [{"entity": "江衡", "statement": "江衡的猫叫小黑。", "value": "小黑"}]
        for question, gold in book_hits:
            if question.startswith("江衡"):
                reply = answer_stated_question(question, extra) or {}
                answer = reply.get("text") or ""
            else:
                answer = _text(question, BOOK)
            if gold in answer:
                correct += 1
            else:
                wrong.append((question, gold, answer))
        self.assertGreaterEqual(correct, BASELINE, wrong)
        self.assertEqual(correct, BASELINE, wrong)

    def test_missing_hop_and_near_name_do_not_cite_another_value(self):
        cases = [
            ("柯岚的妻子叫什么？", "柯岚"),
            ("灯塔守护者的爱人是谁？", "柯岚"),
            ("柯小满养的狗叫什么？", "阿哨"),
            ("江晚川的女儿叫什么？", "江小满"),
            ("诺丁的女儿叫什么？", "柯小满"),
        ]
        near = BOOK + [{"entity": "江晚", "statement": "江晚的女儿是江小满。", "value": "江小满"}]
        for question, forbidden in cases:
            answer = _text(question, near)
            self.assertNotIn(forbidden, answer, question)
            self.assertIn("不在记忆里", answer, question)

    def test_choice_and_capitals(self):
        answer = _text("江小满的自行车是天青色还是墨黑？", [
            {"entity": "江小满", "statement": "江小满的自行车是天青色。", "value": "天青色"},
        ])
        self.assertIn("天青", answer)
        self.assertNotIn("墨黑", answer)
        self.assertEqual(world_reply("墨西哥的首都是哪里？", []), "墨西哥城。")
        self.assertEqual(world_reply("法国的首都是哪里？", []), "巴黎。")
        self.assertEqual(world_reply("青岚国的首都是哪里？", []), "我不知道。")
        self.assertEqual(world_reply("泽川工坊的创始人是谁？", []), "我不知道。")
        self.assertIsNone(world_reply("水的化学式是什么？", []))

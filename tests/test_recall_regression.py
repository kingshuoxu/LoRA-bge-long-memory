"""自己的回忆集。答对的题数不能少于 0.2.35 在同一组题上的分数。

0.2.35 在这组书上改写和人物回忆上答对 261。少一题就失败。
"""
import unittest

from memory_core.blind_heldout import (
    _DAUGHTER_CHAINS,
    _GUARD_NOT_MAKE,
    _KEEPER_CALLED,
    _SALT_TOWERS,
    _WHO_MADE,
    charged_grinders,
    diverse_guards,
    diverse_towers,
    duty_lighthouse_names,
    duty_watchers,
    generate,
    gull_father_towers,
    gull_owner_makers,
    named_by_clause,
    named_towers,
    omitted_tower_guards,
    relative_makers,
)
from memory_core.correct import utterance_is_question
from memory_core.extract import pattern_extract
from memory_core.fact_reader import answer_stated_question, read_memory
from memory_core.unseen_personas import build
from memory_core.world_facts import world_reply

# desktop-v0.2.35 scored 261 on this set (248 book paraphrases + 13 persona recalls).
BASELINE = 261

BOOK = [
    {"entity": "白鹭塔", "statement": "柯岚在雾港守护的第一座灯塔名叫白鹭塔，建于1873年，塔高四十二米。", "value": "白鹭塔"},
    {"entity": "星砂盐", "statement": "雾港的特产是一种蓝色海盐，名叫星砂盐，每年霜降那天开始晾晒。", "value": "星砂盐"},
    {"entity": "阿哨", "statement": "柯岚的女儿柯小满养了一只三条腿的海鸥，名叫阿哨。", "value": "阿哨"},
    {"entity": "诺丁", "statement": "1931年白鹭塔的灯改用电灯，透镜由瑞典工匠诺丁打磨，一共有十六面。", "value": "诺丁"},
]


def _text(question: str, facts: list[dict]) -> str:
    hit = read_memory(question, facts, None) or {}
    return hit.get("text") or ""


def _book_questions() -> list[tuple[str, str]]:
    rows = [(item["q"], item["gold"]) for item in generate(20261216)["taught"]]
    rows.extend(_DAUGHTER_CHAINS)
    rows.extend(_SALT_TOWERS)
    rows.extend((question, "柯岚") for question, _gold in _GUARD_NOT_MAKE)
    rows.extend(_KEEPER_CALLED)
    rows.extend(_WHO_MADE)
    rows.extend((question, "柯岚") for question in diverse_guards())
    rows.extend((question, "柯岚") for question in duty_watchers())
    rows.extend((question, "白鹭塔") for question in named_towers())
    rows.extend((question, "柯岚") for question in omitted_tower_guards())
    rows.extend(relative_makers())
    rows.extend((question, "白鹭塔") for question in gull_father_towers())
    rows.extend(gull_owner_makers())
    rows.extend((question, "白鹭塔") for question in duty_lighthouse_names())
    rows.extend((question, "白鹭塔") for question in named_by_clause())
    rows.extend(charged_grinders())
    rows.extend((question, "白鹭塔") for question in diverse_towers())
    return rows


class RecallRegressionTests(unittest.TestCase):
    def test_correct_answers_do_not_drop_below_v035(self):
        spec = build()
        persona = [
            {"entity": convo["title"], "statement": sentence, "value": sentence}
            for convo in spec["zh"]
            for sentence in convo["sentences"]
        ]
        correct = 0
        for question, gold in _book_questions():
            if gold in _text(question, BOOK):
                correct += 1
        for question, gold in spec["zh_recall"]:
            if gold in _text(question, persona):
                correct += 1
        self.assertGreaterEqual(correct, BASELINE, f"答对 {correct}，0.2.35 是 {BASELINE}")

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

    def test_same_fact_question_and_reported_speech(self):
        self.assertFalse(utterance_is_question("她告诉我她住在南埠。"))
        self.assertFalse(utterance_is_question("我的猫叫咪咪"))
        color = answer_stated_question("我的自行车是朱红色。什么颜色？", pattern_extract("我的自行车是朱红色。什么颜色？")) or {}
        self.assertIn("朱红", color.get("text") or "")
        owner = answer_stated_question("江衡的猫叫小黑。小黑的主人是谁？", pattern_extract("江衡的猫叫小黑。小黑的主人是谁？")) or {}
        self.assertIn("江衡", owner.get("text") or "")
        named = answer_stated_question("江衡的猫叫小黑，它叫什么名字？", pattern_extract("江衡的猫叫小黑，它叫什么名字？")) or {}
        self.assertIn("小黑", named.get("text") or "")
        self.assertTrue(utterance_is_question("我的自行车是朱红色，什么颜色"))
        bare = answer_stated_question("我的自行车是朱红色，什么颜色", pattern_extract("我的自行车是朱红色，什么颜色")) or {}
        self.assertIn("朱红", bare.get("text") or "")

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

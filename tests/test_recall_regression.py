"""自己的回忆集。图走通的关系，和摘录能对上的改写，都不能再少。

少一题就失败。训练后的回忆由安装包里的训练检查负责，不靠这里的解析器代替。
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

# 0.2.35 scored 261 here, including answers whose type was not checked.
# This floor is the same set after nationality/pet/date/place checks. Do not go lower.
BASELINE = 258

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

    def test_reader_requires_exact_subject_and_attribute(self):
        book = BOOK + [{"entity": "江晚", "statement": "江晚的女儿是江小满。", "value": "江小满"}]
        doubled = _text("江晚晚的女儿叫什么？", book)
        self.assertNotIn("江小满", doubled)
        self.assertIn("不在记忆里", doubled)
        red = _text("红色的白鹭塔叫什么？", BOOK)
        self.assertNotIn("白鹭塔", red)
        other_year = _text("白鹭塔哪一年拆除？", BOOK)
        self.assertNotIn("1873", other_year)
        self.assertNotIn("1931", other_year)

    def test_same_fact_question_and_reported_speech(self):
        self.assertFalse(utterance_is_question("她告诉我她住在南埠。"))
        self.assertFalse(utterance_is_question("我的猫叫咪咪"))
        color = answer_stated_question("我的自行车是朱红色。什么颜色？", pattern_extract("我的自行车是朱红色。什么颜色？")) or {}
        self.assertIn("朱红", color.get("text") or "")
        owner = answer_stated_question("江衡的猫叫小黑。小黑的主人是谁？", pattern_extract("江衡的猫叫小黑。小黑的主人是谁？")) or {}
        self.assertIn("江衡", owner.get("text") or "")
        named = answer_stated_question("江衡的猫叫小黑，它叫什么名字？", pattern_extract("江衡的猫叫小黑，它叫什么名字？")) or {}
        self.assertIn("小黑", named.get("text") or "")
        self.assertIn("江衡", (answer_stated_question("江衡的猫叫小黑。它的主人是谁？", pattern_extract("江衡的猫叫小黑。它的主人是谁？")) or {}).get("text") or "")
        white = answer_stated_question("灯塔是白色的。什么颜色？", pattern_extract("灯塔是白色的。什么颜色？")) or {}
        self.assertIn("白", white.get("text") or "")
        self.assertTrue(utterance_is_question("我的自行车是朱红色，什么颜色"))
        bare = answer_stated_question("我的自行车是朱红色，什么颜色", pattern_extract("我的自行车是朱红色，什么颜色")) or {}
        self.assertIn("朱红", bare.get("text") or "")
        other = answer_stated_question("我的自行车是朱红色。它是哪年买的？", pattern_extract("我的自行车是朱红色。它是哪年买的？")) or {}
        self.assertNotIn("朱红", other.get("text") or "")

    def test_choice_and_capitals(self):
        answer = _text("江小满的自行车是天青色还是墨黑？", [
            {"entity": "江小满", "statement": "江小满的自行车是天青色。", "value": "天青色"},
        ])
        self.assertIn("天青", answer)
        self.assertNotIn("墨黑", answer)
        short = _text("江小满的车是天青色还是墨黑？", [
            {"entity": "江小满", "statement": "江小满的自行车是天青色。", "value": "天青色"},
        ])
        self.assertIn("天青", short)
        brand = _text("江小满的自行车是飞鸽还是永久", [
            {"entity": "江小满", "statement": "江小满的自行车品牌是飞鸽。", "value": "飞鸽"},
            {"entity": "江小满", "statement": "江小满的自行车是天青色。", "value": "天青色"},
        ])
        self.assertIn("飞鸽", brand)
        self.assertNotIn("天青", brand)
        self.assertEqual(world_reply("墨西哥的首都是哪里？", []), "墨西哥城。")
        self.assertEqual(world_reply("法国的首都是哪里？", []), "巴黎。")
        self.assertEqual(world_reply("青岚国的首都是哪里？", []), "我不知道。")
        self.assertEqual(world_reply("泽川工坊的创始人是谁？", []), "我不知道。")
        self.assertIsNone(world_reply("水的化学式是什么？", []))
        self.assertEqual(world_reply("月亮是行星还是卫星？", []), "卫星。")
        self.assertEqual(world_reply("月亮是卫星还是行星？", []), "卫星。")
        self.assertEqual(world_reply("水是化合物还是元素？", []), "我不知道。")
        self.assertEqual(world_reply("诺丁是干什么的？", []), "我不知道。")
        self.assertEqual(world_reply("阿哨是什么动物？", []), "我不知道。")

    def test_premise_subject_is_not_the_other_role(self):
        from memory_core.blind_heldout import omitted_tower_guards

        for question in (
            "柯岚是看守。谁是接班人？",
            "柯岚担任看守。接班的那位是谁？",
            "柯岚在值守。谁负责接班？",
            "既然柯岚是看守，谁来接班？",
            "看守是柯岚。谁是接班人？",
        ):
            answer = _text(question, BOOK)
            self.assertNotEqual(answer.strip().rstrip("。"), "柯岚", question)
            self.assertNotIn("柯岚。", answer, question)
        for question in omitted_tower_guards():
            self.assertIn("柯岚", _text(question, BOOK), question)
        daughter = _text("柯岚是这座塔的看守。守护者的女儿是谁？", BOOK)
        self.assertIn("柯小满", daughter)
        father = _text("柯小满是养鸟的人。谁是她父亲？", BOOK)
        self.assertIn("柯岚", father)

    def test_same_turn_year_and_owner(self):
        wrong = answer_stated_question(
            "衡泽工坊成立于2008年。它是2012年成立的吗？",
            pattern_extract("衡泽工坊成立于2008年。它是2012年成立的吗？"),
        ) or {}
        self.assertTrue(str(wrong.get("text") or "").startswith("不是"), wrong)
        self.assertIn("2008", wrong.get("text") or "")
        right = answer_stated_question(
            "衡泽工坊成立于2008年。是2008年成立的吗？",
            pattern_extract("衡泽工坊成立于2008年。是2008年成立的吗？"),
        ) or {}
        self.assertTrue(str(right.get("text") or "").startswith("是"), right)
        self.assertNotIn("不在记忆里", right.get("text") or "")
        for question, gold in (
            ("这辆自行车是江衡的。主人是谁？", "江衡"),
            ("江衡有一本词典。它的主人是谁？", "江衡"),
            ("江衡买了这辆自行车。车主是谁？", "江衡"),
            ("这台机器归江衡所有。拥有者是谁？", "江衡"),
            ("磨豆机的主人是罗知微。谁是主人？", "罗知微"),
        ):
            answer = (answer_stated_question(question, pattern_extract(question)) or {}).get("text") or ""
            self.assertIn(gold, answer, question)
        color = (answer_stated_question("灯塔是白色的。主人是谁？", pattern_extract("灯塔是白色的。主人是谁？")) or {}).get("text") or ""
        self.assertNotIn("白色", color)
        self.assertNotIn("灯塔", color)

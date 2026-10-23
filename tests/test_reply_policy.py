"""已知实体只回答记住的取值，不借用别的属性，也不把是非题说成「是」。"""
import unittest

from memory_core.correct import propose_from_records, _about_someone_else, _matched_someone_else
from memory_core.extract import pattern_extract
from memory_core.grounding import acknowledge_statement, resolve_stored_reply
from memory_core.paraphrase import polar_reply_from_fact


def _fact(entity, attr, value, statement):
    return {
        "id": attr,
        "entity": entity,
        "attr": attr,
        "value": value,
        "answer": value,
        "statement": statement,
    }


class _Expert:
    def __init__(self, facts):
        self.name = "expert"
        self.display_name = "、".join(dict.fromkeys(fact["entity"] for fact in facts))
        self.entities = list(dict.fromkeys(fact["entity"] for fact in facts))
        self.fact_memory = {"facts": facts}
        self.explicit = True


BAI = [
    _fact("柏若岚", "猫的名字", "团子", "柏若岚的猫叫团子。"),
    _fact("柏若岚", "住址", "临溪市", "柏若岚住在临溪市。"),
    _fact("柏若岚", "职业", "陶艺师", "柏若岚的职业是陶艺师。"),
    _fact("柏若岚", "最喜欢的花", "栀子花", "柏若岚最喜欢的花是栀子花。"),
    _fact("柏若岚", "汽车颜色", "酒红色", "柏若岚的汽车是酒红色的。"),
    _fact("柏若岚", "家乡", "梧桐镇", "柏若岚的家乡是梧桐镇。"),
    _fact("柏若岚", "最喜欢的乐器", "琵琶", "柏若岚最喜欢的乐器是琵琶。"),
]
XING = [
    _fact("星禾科技", "成立", "2011年", "星禾科技成立于2011年。"),
    _fact("星禾科技", "总部", "苏州", "星禾科技的总部在苏州。"),
    _fact("星禾科技", "创始人", "韩亦舟", "星禾科技的创始人是韩亦舟。"),
    _fact("星禾科技", "狗的名字", "栗子", "星禾科技养了一只狗叫栗子。"),
]
THEO = [
    _fact("Theodora Quill", "parrot's name", "Saffron", "Theodora Quill's parrot is named Saffron."),
    _fact("Theodora Quill", "where they live", "Ashgrove", "Theodora Quill lives in Ashgrove."),
    _fact("Theodora Quill", "job", "marine biologist", "Theodora Quill works as a marine biologist."),
    _fact("Theodora Quill", "hometown", "Port Ellery", "Theodora Quill's hometown is Port Ellery."),
    _fact("Theodora Quill", "instrument", "oboe", "Theodora Quill plays the oboe."),
]


class ReplyPolicyTests(unittest.TestCase):
    def setUp(self):
        self.experts = [_Expert(BAI + XING), _Expert(THEO)]

    def answer(self, question, mentions=None):
        resolved = resolve_stored_reply(question, self.experts, mentions or [])
        self.assertIsNotNone(resolved, question)
        return resolved[0]

    def test_value_questions_do_not_dump_the_overview(self):
        cases = {
            "柏若岚现居哪座城市？": "临溪市",
            "柏若岚是做什么工作的？": "陶艺师",
            "柏若岚靠什么手艺谋生？": "陶艺师",
            "柏若岚老家是哪里？": "梧桐镇",
            "柏若岚是在哪里长大的？": "梧桐镇",
            "星禾科技是哪一年创立的？": "2011",
            "星禾科技总部设在哪个城市？": "苏州",
            "星禾科技是谁创办的？": "韩亦舟",
            "星禾科技养的狗叫什么？": "栗子",
            "What does Theodora Quill do for a living?": "marine biologist",
            "Where is Theodora Quill originally from?": "Port Ellery",
            "Which musical instrument does Theodora Quill play?": "oboe",
            "Which town is Theodora Quill living in?": "Ashgrove",
        }
        for question, gold in cases.items():
            reply = self.answer(question)
            self.assertIn(gold, reply, (question, reply))
            self.assertNotIn("记住的是", reply, question)
            self.assertNotIn("what I have stored", reply.casefold(), question)

    def test_wrong_attribute_abstains(self):
        for question in (
            "柏若岚的猫几岁了？",
            "柏若岚最讨厌的花是什么？",
            "柏若岚多高？",
            "How old is Theodora Quill's parrot?",
            "What is Theodora Quill's email address?",
        ):
            reply = self.answer(question)
            self.assertTrue("不在记忆里" in reply or "not in memory" in reply.casefold(), (question, reply))
            for borrowed in ("团子", "栀子花", "Saffron", "Ashgrove", "琵琶"):
                self.assertNotEqual(reply.strip("。."), borrowed, question)

    def test_yes_no_compares_the_asked_value(self):
        self.assertTrue(self.answer("星禾科技的创始人是马云吗？").startswith("不是"))
        self.assertTrue(self.answer("柏若岚的车是墨绿色的吗？").startswith("不是"))
        self.assertIn("酒红色", self.answer("柏若岚的车是墨绿色的吗？"))
        self.assertTrue(self.answer("柏若岚住在临溪市吗？").startswith("是"))
        self.assertTrue(self.answer("柏若岚是医生吗？").startswith("不是"))
        self.assertTrue(self.answer("柏若岚会弹古筝吗？").startswith("不是"))
        self.assertIn("琵琶", self.answer("柏若岚会弹古筝吗？"))
        self.assertTrue(polar_reply_from_fact("沈星河的猫是不是叫云朵？", {"value": "云朵"}).startswith("是"))
        self.assertTrue(polar_reply_from_fact("沈星河的猫是不是叫可乐？", {"value": "云朵"}).startswith("不是"))

    def test_open_question_still_lists_stored_facts(self):
        reply = self.answer("告诉我星禾科技相关信息")
        self.assertIn("韩亦舟", reply)
        self.assertIn("不在记忆里", reply)

    def test_mentioned_entity_without_facts_does_not_need_a_stored_fact(self):
        reply = self.answer("When was Brightwater Labs founded?", ["Brightwater Labs"])
        self.assertIn("not in memory", reply.casefold())

    def test_birthday_stays_an_abstain(self):
        reply = self.answer("柏若岚的生日是什么时候？")
        self.assertIn("不在记忆里", reply)
        self.assertNotIn("团子", reply)

    def test_acknowledgement_grammar(self):
        color = pattern_extract("我最喜欢的颜色是蓝色。")[0]
        self.assertEqual(acknowledge_statement(color), "好，你最喜欢的颜色是蓝色。")
        cat = pattern_extract("我的猫猫叫咪咪")[0]
        self.assertEqual(acknowledge_statement(cat), "好，你的猫叫咪咪。")
        english = pattern_extract("My favorite color is blue.")[0]
        self.assertEqual(acknowledge_statement(english), "Got it, your favorite color is blue.")
        swapped = pattern_extract("Blue is my favorite color.")[0]
        self.assertIn("your", acknowledge_statement(swapped).casefold())
        self.assertNotIn(" my ", f" {acknowledge_statement(swapped).casefold()} ")

    def test_existing_persona_paraphrases_still_return_the_value(self):
        facts = [
            _fact("沈星河", "猫的名字", "云朵", "沈星河的猫的名字是云朵。"),
            _fact("沈星河", "住址", "青岚镇", "沈星河的住址是青岚镇。"),
            _fact("沈星河", "自行车颜色", "朱红色", "沈星河的自行车颜色是朱红色。"),
            _fact("沈星河", "最喜欢的茶", "桂花乌龙", "沈星河最喜欢的茶是桂花乌龙。"),
        ]
        expert = _Expert(facts)
        hits = {
            "沈星河养的那只猫叫什么名字？": "云朵",
            "沈星河家的猫咪叫啥？": "云朵",
            "沈星河住哪儿？": "青岚镇",
            "沈星河居住在什么地方？": "青岚镇",
            "沈星河自行车是什么色的？": "朱红色",
            "沈星河最爱喝的茶是哪种？": "桂花乌龙",
            "What is Mira Chen's cat's name?": None,
        }
        mira = _Expert([
            _fact("Mira Chen", "cat's name", "Snow", "Mira Chen's cat's name is Snow."),
            _fact("Mira Chen", "where they live", "Qinglan", "Mira Chen lives in Qinglan."),
            _fact("Mira Chen", "bicycle color", "vermilion", "Mira Chen's bicycle color is vermilion."),
        ])
        for question, gold in hits.items():
            if gold is None:
                continue
            resolved = resolve_stored_reply(question, [expert], [])
            self.assertIsNotNone(resolved, question)
            self.assertIn(gold, resolved[0], (question, resolved[0]))
        for question, gold in (
            ("Where does Mira Chen live?", "Qinglan"),
            ("What colour is Mira Chen's bicycle?", "vermilion"),
            ("What is the cat's name of Mira Chen?", "Snow"),
        ):
            resolved = resolve_stored_reply(question, [mira], [])
            self.assertIsNotNone(resolved, question)
            self.assertIn(gold, resolved[0], (question, resolved[0]))
        for question in (
            "沈星河的狗叫什么？",
            "沈星河的生日是什么时候？",
            "沈星河会弹古筝吗？",
            "沈星河的电话是多少？",
            "沈星河喜欢吃什么？",
            "沈星河的单车是什么颜色？",
            "沈星河的车是什么颜色？",
        ):
            resolved = resolve_stored_reply(question, [expert], [])
            self.assertIsNotNone(resolved, question)
            self.assertIn("不在记忆里", resolved[0], (question, resolved[0]))
            self.assertNotIn("云朵", resolved[0])
            self.assertNotIn("桂花乌龙", resolved[0])
            self.assertNotIn("朱红色", resolved[0])

    def test_first_person_statement_is_not_a_correction(self):
        expert = _Expert(BAI)
        expert.writable = True
        proposal = propose_from_records("我的猫猫叫咪咪", [expert], model=object(), tok=object(), device="cpu")
        self.assertIsNone(proposal)

    def test_another_persons_statement_is_not_a_correction(self):
        shen = _Expert([_fact("沈星河", "猫的名字", "云朵", "沈星河的猫叫云朵。")])
        shen.writable = True
        self.assertTrue(_about_someone_else("昭澈的猫叫阿栗。", [shen]))
        self.assertTrue(_matched_someone_else("昭澈的猫叫阿栗。", "沈星河"))
        self.assertFalse(_matched_someone_else("沈星河的猫的名字不是云朵，正确的是暮雪。", "沈星河"))
        proposal = propose_from_records("昭澈的猫叫阿栗。", [shen], model=object(), tok=object(), device="cpu")
        self.assertIsNone(proposal)


if __name__ == "__main__":
    unittest.main()

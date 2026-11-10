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
        self.assertTrue("不记得" in reply or "不在记忆里" in reply, reply)
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
            self.assertTrue(
                any(mark in resolved[0] for mark in ("不在记忆里", "不记得", "没提到")),
                (question, resolved[0]),
            )
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
        self.assertFalse(_matched_someone_else(
            "The name of Marcus Whitfield's dog is Waffles, not Biscuit.",
            "Marcus Whitfield",
        ))
        proposal = propose_from_records("昭澈的猫叫阿栗。", [shen], model=object(), tok=object(), device="cpu")
        self.assertIsNone(proposal)

    def test_color_product_and_yes_no_use_the_stored_fact(self):
        person = _Expert([
            _fact("周衡", "汽车", "珍珠白的", "周衡的汽车是珍珠白的。"),
            _fact("周衡", "自行车颜色", "朱红色", "周衡的自行车是朱红色的。"),
            _fact("周衡", "鹦鹉", "小翠", "周衡的鹦鹉叫小翠。"),
        ])
        org = _Expert([
            _fact("北窗茶舍", "主打产品", "陶瓷滤杯", "北窗茶舍的主打产品是陶瓷滤杯。"),
            _fact("北窗茶舍", "狗的名字", "阿黄", "北窗茶舍养了一只狗，名字叫阿黄。"),
        ])
        ada = _Expert([
            _fact("Ada Liu", "job", "conservator of manuscripts", "Ada Liu works as a conservator of manuscripts."),
            _fact("Ada Liu", "where they live", "Ashmere", "Ada Liu lives in Ashmere."),
        ])
        press = _Expert([
            _fact("Northwind Press", "founder", "Ida Okada", "Northwind Press was founded by Ida Okada."),
            _fact("Northwind Press", "flagship product", "linen notebooks", "Northwind Press' flagship product is linen notebooks."),
            _fact("Northwind Press", "office cat's name", "Miso", "Northwind Press has an office cat named Miso."),
        ])
        experts = [person, org, ada, press]

        def reply(question):
            resolved = resolve_stored_reply(question, experts, [])
            self.assertIsNotNone(resolved, question)
            return resolved

        color = reply("周衡的汽车是什么颜色？")
        self.assertIn("珍珠白", color[0])
        self.assertEqual(color[3], "entity_first")
        short = reply("周衡开的车是什么颜色？")
        self.assertIn("珍珠白", short[0])
        same = reply("周衡的车是什么颜色？")
        self.assertIn("珍珠白", same[0])
        self.assertNotIn("朱红", same[0])
        slang = reply("周衡的车啥颜色？")
        self.assertIn("珍珠白", slang[0])
        self.assertNotIn("朱红", slang[0])
        cycle = _Expert([_fact("周衡", "自行车颜色", "朱红色", "周衡的自行车是朱红色的。")])
        for question in ("周衡的车是什么颜色？", "周衡的车啥颜色？", "周衡的单车是什么颜色？", "周衡开的车是什么颜色？"):
            missed = resolve_stored_reply(question, [cycle], [])
            self.assertIsNotNone(missed, question)
            self.assertIn("不在记忆里", missed[0], (question, missed[0]))
            self.assertNotIn("朱红", missed[0], question)
        parrot = reply("周衡的鹦鹉叫什么？")
        self.assertIn("小翠", parrot[0])
        product = reply("北窗茶舍主打什么产品？")
        self.assertIn("陶瓷滤杯", product[0])
        self.assertNotIn("记住的是", product[0])
        self.assertTrue(reply("北窗茶舍的狗叫阿黄吗？")[0].startswith("是"))
        self.assertTrue(reply("北窗茶舍的狗是不是叫旺财？")[0].startswith("不是"))
        self.assertTrue(reply("Is Ada Liu a conservator of manuscripts?")[0].casefold().startswith("yes"))
        surgeon = reply("Is Ada Liu a surgeon?")
        self.assertTrue(surgeon[0].casefold().startswith("no"))
        self.assertIn("conservator of manuscripts", surgeon[0])
        self.assertIn("Ashmere", reply("Where does Ada Liu reside?")[0])
        self.assertTrue(reply("Did Ida Okada found Northwind Press?")[0].casefold().startswith("yes"))
        stranger = reply("Did Ada Lovelace found Northwind Press?")
        self.assertTrue(stranger[0].casefold().startswith("no"))
        self.assertIn("Ida Okada", stranger[0])
        self.assertTrue(reply("Is the Northwind Press office cat named Miso?")[0].casefold().startswith("yes"))
        flagship = reply("What is Northwind Press' flagship product?")
        self.assertIn("linen notebooks", flagship[0])
        self.assertNotIn("what i have stored", flagship[0].casefold())
        self.assertEqual(flagship[3], "entity_first")
        overview = reply("Give me an overview of Northwind Press")
        self.assertEqual(overview[3], "entity_overview")
        self.assertIn("linen notebooks", overview[0])
        self.assertIn("not in memory", overview[0].casefold())
        everything = reply("Tell me everything about Ada Liu")
        self.assertEqual(everything[3], "entity_overview")
        self.assertIn("Ashmere", everything[0])
        near = reply("周衡兰的猫叫什么？")
        self.assertEqual(near[3], "entity_clarify")
        self.assertNotIn("小翠", near[0])
        suffix = reply("Who founded Northwind Press Inc?")
        self.assertEqual(suffix[3], "entity_clarify")
        self.assertNotIn("Ida Okada", suffix[0])
        self.assertNotIn("linen notebooks", suffix[0])

    def test_old_expert_says_to_consolidate_again(self):
        legacy = _Expert([
            _fact("周衡", "鹦鹉的名字", "小翠", "周衡的鹦鹉叫小翠。"),
        ])
        legacy.explicit = False
        legacy.fact_memory = {"facts": legacy.fact_memory["facts"], "legacy": True}
        hit = resolve_stored_reply("周衡的鹦鹉叫什么？", [legacy], [])
        self.assertIsNotNone(hit)
        self.assertIn("小翠", hit[0])
        missed = resolve_stored_reply("周衡的电话是多少？", [legacy], [])
        self.assertIsNotNone(missed)
        self.assertIn("重新巩固", missed[0])
        self.assertNotIn("不在记忆里", missed[0])
        self.assertEqual(missed[3], "legacy_retrain")

    def test_near_miss_clarifies_and_paraphrase_still_hits(self):
        from memory_core.fact_span import name_bounded, near_miss_span
        from memory_core.grounding import forget_fact_hit

        person = _Expert([
            _fact("周衡川", "兔子的名字", "豆青", "周衡川的兔子叫豆青。"),
            _fact("周衡川", "住址", "听潮市", "周衡川住在听潮市。"),
            _fact("周衡川", "最喜欢的花", "紫藤花", "周衡川最喜欢的花是紫藤花。"),
            _fact("周衡川", "汽车颜色", "藏青色", "周衡川的汽车是藏青色的。"),
            _fact("周衡川", "家乡", "青柘镇", "周衡川的家乡是青柘镇。"),
        ])
        org = _Expert([
            _fact("北窗智造", "成立", "2004年", "北窗智造成立于2004年。"),
            _fact("北窗智造", "总部", "湖州", "北窗智造的总部在湖州。"),
            _fact("北窗智造", "创始人", "叶晚照", "北窗智造的创始人是叶晚照。"),
            _fact("北窗智造", "主打产品", "手动磨豆机", "北窗智造的主打产品是手动磨豆机。"),
        ])
        experts = [person, org]

        def reply(question):
            resolved = resolve_stored_reply(question, experts, [])
            self.assertIsNotNone(resolved, question)
            return resolved

        year = reply("北窗智造成立于哪一年？")
        self.assertIn("2004", year[0])
        self.assertEqual(year[3], "entity_first")
        flower = reply("周衡川偏爱哪种花？")
        self.assertIn("紫藤花", flower[0])
        self.assertEqual(flower[3], "entity_first")
        color = reply("周衡川的车啥颜色？")
        self.assertIn("藏青", color[0])
        self.assertEqual(color[3], "entity_first")
        product = reply("北窗智造主要卖什么产品？")
        self.assertIn("手动磨豆机", product[0])
        self.assertEqual(product[3], "entity_first")
        school = reply("周衡川毕业于哪所大学？")
        self.assertTrue("不在记忆里" in school[0] or "没记过" in school[0], school[0])
        self.assertNotIn("豆青", school[0])
        self.assertEqual(school[0], "我没记过周衡川的学校。")
        self.assertEqual(school[3], "entity_grounded")
        overview = reply("overview of 周衡川")
        self.assertEqual(overview[3], "entity_overview")
        self.assertIn("豆青", overview[0])
        everything = reply("everything about 北窗智造")
        self.assertEqual(everything[3], "entity_overview")
        self.assertIn("手动磨豆机", everything[0])
        for question, banned in (
            ("周衡的家乡是哪里？", "青柘"),
            ("周衡春住在哪里？", "听潮"),
            ("北窗制造成立于哪一年？", "2004"),
            ("北窗智造公司 Inc 的创始人是谁？", "叶晚照"),
            ("北窗智造集团的总部在哪里？", "湖州"),
            ("overview of 周衡", "豆青"),
            ("everything about 北窗制造", "手动磨豆机"),
            ("周衡川兰的兔子叫什么？", "豆青"),
        ):
            got = reply(question)
            self.assertEqual(got[3], "entity_clarify", (question, got[0]))
            self.assertNotIn(banned, got[0], (question, got[0]))
        self.assertTrue(name_bounded("佐雷", "佐雷公司是哪一年成立的？"))
        self.assertIsNone(near_miss_span("佐雷", "佐雷公司是哪一年成立的？"))
        self.assertFalse(name_bounded("星禾", "告诉我星禾科技相关信息"))
        self.assertEqual(near_miss_span("星禾", "告诉我星禾科技相关信息"), "星禾科技")
        self.assertEqual(near_miss_span("北窗工坊", "北窗工社成立于哪一年？"), "北窗工社")
        self.assertEqual(near_miss_span("周衡川", "周衡的家乡是哪里？"), "周衡")
        from memory_core.correct import utterance_is_question

        self.assertTrue(utterance_is_question("Tell me everything about Ada Liu"))
        self.assertTrue(utterance_is_question("Give me an overview of Northwind Press"))
        self.assertTrue(utterance_is_question("overview of 周衡川"))
        self.assertTrue(utterance_is_question("everything about 北窗智造"))
        self.assertTrue(utterance_is_question("告诉我北窗智造相关信息"))
        self.assertFalse(utterance_is_question("Ada Liu lives in Paris, not Rome."))
        self.assertIsNone(propose_from_records(
            "Tell me everything about Ada Liu",
            experts,
            model=object(),
            tok=object(),
            device="cpu",
        ))
        self.assertFalse(name_bounded("北窗智造", "北窗智造公司 Inc 的创始人是谁？"))
        self.assertIn("Inc", near_miss_span("北窗智造", "北窗智造公司 Inc 的创始人是谁？"))
        person = _Expert([
            _fact("Nadia Pell", "car", "sage green", "Nadia Pell's car is sage green."),
            _fact("Nadia Pell", "where they live", "Brindle", "Nadia Pell lives in Brindle."),
            _fact("Nadia Pell", "hometown", "Redwick", "Nadia Pell's hometown is Redwick."),
        ])
        org = _Expert([
            _fact("Copperline Studio", "headquarters", "Halver", "Copperline Studio is headquartered in Halver."),
            _fact("Copperline Studio", "founder", "Ida Okada", "Copperline Studio was founded by Ida Okada."),
        ])
        experts = [person, org]

        def reply(question):
            resolved = resolve_stored_reply(question, experts, [])
            self.assertIsNotNone(resolved, question)
            return resolved

        for question in (
            "What color is Nadia Pell's car?",
            "What colour is Nadia Pell's car?",
            "What color does Nadia Pell's car have?",
        ):
            color = reply(question)
            self.assertIn("sage green", color[0], (question, color[0]))
            self.assertEqual(color[3], "entity_first", question)
        self.assertIn("Brindle", reply("Where does Nadia Pell live?")[0])
        for question, banned in (
            ("Where does Nadia Pel live?", "Brindle"),
            ("What is Nadia Holt's hometown?", "Redwick"),
            ("Where is Copperline Inc headquartered?", "Halver"),
            ("Who founded Copperline Labs?", "Ida Okada"),
        ):
            got = reply(question)
            self.assertEqual(got[3], "entity_clarify", (question, got[0]))
            self.assertNotIn(banned, got[0], (question, got[0]))
        bike = resolve_stored_reply(
            "What color is Nadia Pell's bicycle?",
            [_Expert([_fact("Nadia Pell", "car", "sage green", "Nadia Pell's car is sage green.")])],
            [],
        )
        self.assertIsNotNone(bike)
        self.assertNotIn("sage green", bike[0])
        decision = type("D", (), {"fact_pass": True, "entity_pass": True})()
        recall = {"fact_gate": {"answer_from_fact": True, "matched": True}, "matched_facts": [{"value": "叶晚照"}]}
        forget_fact_hit(decision, recall)
        self.assertFalse(decision.fact_pass)
        self.assertFalse(decision.entity_pass)
        self.assertFalse(recall["fact_gate"]["answer_from_fact"])
        self.assertFalse(recall["fact_gate"]["matched"])
        self.assertEqual(recall["matched_facts"], [])

    def test_corrected_color_paraphrases_return_the_new_value(self):
        from memory_core.correct import reissue_training_fact

        issued = reissue_training_fact(
            _fact("Ida Voss", "car color", "blue", "Ida Voss's car is blue."),
            "amber mist",
        )
        self.assertEqual(issued["attr"], "car color")
        self.assertEqual(issued["value"], "amber mist")
        expert = _Expert([issued])
        for question in (
            "What color is Ida Voss's car?",
            "What colour is Ida Voss's car?",
            "What color does Ida Voss's car have?",
        ):
            got = resolve_stored_reply(question, [expert], [])
            self.assertIsNotNone(got, question)
            self.assertIn("amber mist", got[0], (question, got[0]))
            self.assertNotIn("blue", got[0].casefold(), (question, got[0]))
            self.assertEqual(got[3], "entity_first", question)
        yes = resolve_stored_reply("Is Ida Voss's car amber mist?", [expert], [])
        self.assertTrue(yes[0].casefold().startswith("yes"), yes[0])
        bare = reissue_training_fact(
            _fact("Ida Voss", "car color", "blue", "Ida Voss's car is blue."),
            "haze",
        )
        self.assertEqual(bare["attr"], "car color")
        haze = resolve_stored_reply("What color is Ida Voss's car?", [_Expert([bare])], [])
        self.assertIn("haze", haze[0])
        bike = resolve_stored_reply(
            "What color is Ida Voss's bicycle?",
            [_Expert([bare])],
            [],
        )
        self.assertIsNotNone(bike)
        self.assertNotIn("haze", bike[0])

    def test_shared_fact_id_corrects_the_named_person(self):
        from memory_core.correct import propose_from_records

        def expert(name, entity, value):
            fact = _fact(entity, "car color", value, f"{entity}'s car is {value}.")
            fact["id"] = "f1"
            row = _Expert([fact])
            row.name = name
            row.writable = True
            row.explicit = True
            return row

        first = expert("expert_a", "Ada Liu", "blue")
        second = expert("expert_b", "Ida Voss", "copper")
        got = propose_from_records(
            "Ida Voss's car is amber mist.",
            [first, second],
            fact_id="f1",
            new_value="amber mist",
        )
        self.assertEqual(got["expert"], "expert_b")
        self.assertEqual(got["entity"], "Ida Voss")
        self.assertEqual(got["old_value"], "copper")
        self.assertEqual(got["new_value"], "amber mist")


class OpenTaskTests(unittest.TestCase):
    def test_writing_about_a_birthday_is_not_a_memory_question(self):
        expert = _Expert([_fact("我", "名字", "徐金朔", "我叫徐金朔。")])
        for prompt in ("帮我写一句生日祝福", "帮我写一句给朋友的生日祝福", "你好"):
            self.assertIsNone(resolve_stored_reply(prompt, [expert], []), prompt)

    def test_near_miss_names_the_missing_attribute(self):
        expert = _Expert([_fact("周衡川", "家乡", "青柘镇", "周衡川的家乡是青柘镇。")])
        got = resolve_stored_reply("周衡的家乡是哪里？", [expert], [])
        self.assertEqual(got[3], "entity_clarify")
        self.assertIn("家乡", got[0])
        self.assertNotIn("你说的这件事", got[0])
        self.assertNotIn("青柘", got[0])


LENS = "1931年白鹭塔的灯改用电灯，透镜由瑞典工匠诺丁打磨，一共有十六面。"
TOWER = "柯岚在雾港守护的第一座灯塔名叫白鹭塔，建于1873年，塔高四十二米。"


class AnswerTypeTests(unittest.TestCase):
    def test_craftsman_count_does_not_quote_the_lens_sentence(self):
        from memory_core.fact_recall import spoken_fact
        from memory_core.span_guard import enforce_answer_type

        fact = _fact("透镜", "重点", LENS.rstrip("。"), LENS)
        fact["source"] = "document"
        self.assertEqual(spoken_fact("透镜有多少个工匠？", fact), "")
        gated = enforce_answer_type("透镜有多少个工匠？", LENS, [fact, _fact("我", "名字", "徐金朔", "我叫徐金朔。")])
        self.assertEqual(gated["status"], "abstain")
        self.assertIn("有多少个工匠", gated["text"])
        self.assertNotIn("十六", gated["text"])
        self.assertNotIn("诺丁", gated["text"])
        expert = _Expert([fact])
        got = resolve_stored_reply("透镜有多少个工匠？", [expert], [])
        self.assertTrue(got)
        self.assertNotIn("十六", got[0])
        self.assertNotIn("诺丁", got[0])
        self.assertEqual(got[2], [])

    def test_matching_year_span_stays(self):
        from memory_core.span_guard import enforce_answer_type

        fact = _fact("白鹭塔", "建于", "1873年", TOWER)
        self.assertIsNone(enforce_answer_type("白鹭塔建于哪一年？", "1873年。", [fact]))
        gated = enforce_answer_type("白鹭塔建于哪一年？", TOWER, [fact])
        self.assertEqual(gated["status"], "span")
        self.assertEqual(gated["span"], "1873年")
        unrelated = _fact("我", "名字", "徐金朔", "我叫徐金朔。")
        still = enforce_answer_type("白鹭塔建于哪一年？", TOWER, [unrelated])
        self.assertEqual(still["status"], "span")
        self.assertEqual(still["span"], "1873年")

    def test_who_guards_is_not_the_craftsman_title(self):
        from memory_core.fact_reader import read_memory
        from memory_core.span_guard import span_fits

        facts = [
            {"entity": "白鹭塔", "statement": "柯岚在雾港守护的第一座灯塔名叫白鹭塔，建于1873年，塔高四十二米。", "value": "白鹭塔", "source": "document"},
            {"entity": "诺丁", "statement": "1931年白鹭塔的灯改用电灯，透镜由瑞典工匠诺丁打磨，一共有十六面。", "value": "诺丁", "source": "document"},
            {"entity": "阿哨", "statement": "柯岚的女儿柯小满养了一只三条腿的海鸥，名叫阿哨。", "value": "阿哨", "source": "document"},
        ]
        self.assertFalse(span_fits("谁守护白鹭塔？", "瑞典工匠"))
        got = read_memory("诺丁打磨透镜的那座塔是谁守护的？", facts, None)
        self.assertIn("柯岚", got["text"])
        self.assertNotIn("瑞典工匠", got["text"])
        self.assertFalse(got["miss"])
        missed = read_memory("诺丁的女儿叫什么？", facts, None)
        self.assertTrue(missed is None or missed.get("miss") or "柯小满" not in missed["text"])

    def test_a_count_question_does_not_keep_a_sentence_that_only_contains_ming(self):
        from memory_core.fact_recall import spoken_fact
        from memory_core.span_guard import span_fits

        self.assertFalse(span_fits("白鹭塔建了多少次？", TOWER))
        self.assertTrue(span_fits("白鹭塔建了多少次？", "三次"))
        self.assertEqual(spoken_fact("白鹭塔建了多少次？", _fact("白鹭塔", "重点", TOWER.rstrip("。"), TOWER)), "")
        self.assertEqual(spoken_fact("雾港有多少人口？", _fact("白鹭塔", "重点", TOWER.rstrip("。"), TOWER)), "")

    def test_kinship_tower_and_event_do_not_borrow_another_span(self):
        from memory_core.answer_type import memory_topic
        from memory_core.fact_reader import read_memory

        facts = [
            {"entity": "白鹭塔", "statement": "柯岚在雾港守护的第一座灯塔名叫白鹭塔，建于1873年，塔高四十二米。", "source": "document"},
            {"entity": "星砂盐", "statement": "雾港的特产是一种蓝色海盐，名叫星砂盐，每年霜降那天开始晾晒。", "source": "document"},
            {"entity": "阿哨", "statement": "柯岚的女儿柯小满养了一只三条腿的海鸥，名叫阿哨。", "source": "document"},
            {"entity": "诺丁", "statement": "1931年白鹭塔的灯改用电灯，透镜由瑞典工匠诺丁打磨，一共有十六面。", "source": "document"},
        ]

        def text(question):
            hit = read_memory(question, facts, None) or {}
            return hit.get("text") or ""

        self.assertIn("柯岚", text("柯小满的爸爸叫什么？"))
        self.assertNotIn("阿哨", text("柯小满的爸爸叫什么？"))
        self.assertIn("白鹭塔", text("她爸爸守护的塔叫啥？"))
        self.assertNotIn("阿哨", text("她爸爸守护的塔叫啥？"))
        self.assertIn("白鹭塔", text("十六面透镜是哪座灯塔？"))
        self.assertNotIn("柯岚", text("十六面透镜是哪座灯塔？"))
        self.assertIn("星砂盐", text("每年霜降晾晒的盐叫什么？"))
        self.assertIn("1931", text("柯岚守护的灯塔什么时候改成电灯？"))
        spouse = text("柯岚的太太叫什么？")
        self.assertNotIn("白鹭塔", spouse)
        self.assertIn("没提到", spouse)
        nested = text("柯小满养的鸟的主人的爹叫什么？")
        self.assertIn("柯岚", nested)
        self.assertNotIn("阿哨", nested)
        self.assertIn("白鹭塔", text("有十六面透镜的灯塔是哪一座？"))
        self.assertIn("柯岚", text("塔高四十二米的那座塔是谁守护的？"))
        first = text("柯岚第一次点灯是哪一天？")
        self.assertNotIn("1931", first)
        self.assertTrue(memory_topic("诺丁活到多少岁？", facts))
        self.assertFalse(memory_topic("水的化学式是什么？", facts))

    def test_color_without_the_character_still_answers_the_same_object(self):
        from memory_core.fact_reader import read_memory

        person = [
            _fact("禾昭闻", "猫的名字", "小山", "禾昭闻的猫叫小山。"),
            _fact("禾昭闻", "汽车颜色", "墨黑", "禾昭闻的汽车是墨黑。"),
        ]
        pearl = [_fact("周衡", "汽车颜色", "珍珠白", "周衡的汽车是珍珠白的。")]
        navy = [_fact("许澄", "汽车颜色", "藏青", "许澄的汽车是藏青。")]
        bike = [
            _fact("沈星河", "自行车颜色", "朱红色", "沈星河的自行车颜色是朱红色。"),
            _fact("沈星河", "猫的名字", "云朵", "沈星河的猫的名字是云朵。"),
        ]

        def answer(question, facts):
            return (read_memory(question, facts, None) or {}).get("text") or ""

        for question in ("禾昭闻的汽车是什么颜色？", "禾昭闻开的车是什么颜色？", "禾昭闻的车啥颜色？"):
            text = answer(question, person)
            self.assertIn("墨黑", text, question)
            self.assertNotIn("没记过", text, question)
            self.assertNotIn("小山", text, question)
        self.assertNotIn("墨黑", answer("禾昭闻的猫是什么颜色？", person))
        self.assertNotIn("墨黑", answer("禾昭闻的自行车是什么颜色？", person))
        self.assertIn("珍珠白", answer("周衡开的车是什么颜色？", pearl))
        self.assertIn("藏青", answer("许澄的车啥颜色？", navy))
        self.assertIn("朱红", answer("沈星河那辆自行车是什么颜色？", bike))
        for question in ("沈星河的汽车颜色是什么？", "沈星河的车是什么颜色？", "沈星河开的车是什么颜色？"):
            text = answer(question, bike)
            self.assertNotIn("朱红", text, question)
            self.assertNotIn("云朵", text, question)

    def test_book_memory_does_not_swap_type_role_or_pet(self):
        from memory_core.fact_reader import read_memory

        facts = [
            {"entity": "白鹭塔", "statement": "柯岚在雾港守护的第一座灯塔名叫白鹭塔，建于1873年，塔高四十二米。", "value": "白鹭塔", "source": "document"},
            {"entity": "诺丁", "statement": "1931年白鹭塔的灯改用电灯，透镜由瑞典工匠诺丁打磨，一共有十六面。", "value": "诺丁", "source": "document"},
            {"entity": "阿哨", "statement": "柯岚的女儿柯小满养了一只三条腿的海鸥，名叫阿哨。", "value": "阿哨", "source": "document"},
            {"entity": "星砂盐", "statement": "雾港的特产是一种蓝色的海盐，名叫星砂盐，每年霜降开始晾晒。", "value": "星砂盐", "source": "document"},
        ]

        def answer(question):
            return (read_memory(question, facts, None) or {}).get("text") or ""

        self.assertIn("瑞典", answer("诺丁是哪国人？"))
        self.assertIn("柯岚", answer("谁守护白鹭塔？"))
        self.assertIn("诺丁", answer("谁打磨了透镜？"))
        self.assertIn("柯小满", answer("柯岚的女儿叫什么？"))
        self.assertIn("白鹭塔", answer("雾港有哪座灯塔？"))
        for question in (
            "白鹭塔是哪国的？",
            "瑞典是哪座塔？",
            "白鹭塔在哪个国家？",
            "诺丁是哪座建筑？",
            "柯岚是哪座塔？",
            "雾港是哪座塔？",
        ):
            text = answer(question)
            self.assertTrue("没记过" in text or "不在记忆里" in text or "没提到" in text or "不确定" in text, (question, text))
            self.assertFalse(text.startswith("瑞典") or text.startswith("白鹭塔"), (question, text))
        for question in ("谁建造了白鹭塔？", "白鹭塔的建筑师是谁？", "谁设计了白鹭塔？", "透镜的建造者是谁？"):
            text = answer(question)
            self.assertNotIn("柯岚", text, question)
            self.assertNotIn("诺丁", text, question)
        for question in ("柯岚的兄弟是谁？", "柯小满的姐姐叫什么？", "柯小满的叔叔是谁？", "阿哨的爷爷是谁？"):
            text = answer(question)
            self.assertFalse(text.startswith("阿哨") or text.startswith("柯小满"), (question, text))
            self.assertTrue("没提到" in text or "没记过" in text or "不在记忆里" in text or "不确定" in text, (question, text))


class CrossEntityTests(unittest.TestCase):
    def test_pet_name_is_not_the_school(self):
        from memory_core.fact_reader import read_memory

        school = {"entity": "沈星河", "statement": "沈星河的学校叫青藤中学。", "value": "青藤中学"}
        cat = {"entity": "沈星河", "statement": "沈星河的猫的名字是云朵。", "value": "云朵"}
        both = read_memory("沈星河的猫叫什么名字？", [school, cat], None) or {}
        self.assertIn("云朵", both.get("text") or "")
        self.assertNotIn("青藤", both.get("text") or "")
        only_school = read_memory("沈星河的宠物叫什么名字？", [school], None) or {}
        self.assertNotIn("青藤", only_school.get("text") or "")
        self.assertIn("没记过", only_school.get("text") or "")

    def test_school_question_never_returns_the_cat(self):
        from memory_core.fact_reader import read_memory

        cat = {"entity": "沈星河", "statement": "沈星河的猫的名字是云朵。", "value": "云朵"}
        home = {"entity": "沈星河", "statement": "沈星河的住址是青岚镇。", "value": "青岚镇"}
        school = {"entity": "沈星河", "statement": "沈星河的学校叫青藤中学。", "value": "青藤中学"}
        questions = [
            "沈星河的学校叫什么？",
            "沈星河在哪所学校上学？",
            "沈星河就读的学校叫什么名字？",
            "请问沈星河的学校叫啥？",
            "沈星河的学校的名字是什么？",
            "沈星河毕业于哪所学校？",
        ]
        from memory_core.span_guard import refusal_dangling

        for question in questions:
            answer = (read_memory(question, [cat, home], None) or {}).get("text") or ""
            self.assertNotIn("云朵", answer, question)
            self.assertNotIn("青岚", answer, question)
            self.assertIn("没记过", answer, question)
            self.assertEqual(refusal_dangling(answer), "", answer)
            known = (read_memory(question, [cat, home, school], None) or {}).get("text") or ""
            self.assertIn("青藤中学", known, question)
            self.assertNotIn("云朵", known, question)
        for question in ("周晚宁的学校叫什么？", "周晚宁就读的学校叫什么名字？"):
            answer = (read_memory(question, [cat, home, school], None) or {}).get("text") or ""
            self.assertNotIn("云朵", answer, question)
            self.assertNotIn("青藤", answer, question)
            self.assertEqual(refusal_dangling(answer), "", answer)
        for question in ("沈星河的猫叫什么名字？", "沈星河养的那只猫叫什么名字？", "沈星河家的猫咪叫啥？"):
            answer = (read_memory(question, [cat, home, school], None) or {}).get("text") or ""
            self.assertIn("云朵", answer, question)
            self.assertNotIn("青藤", answer, question)

    def test_abstain_wording_keeps_the_attribute(self):
        from memory_core.span_guard import fixed_refusal, refusal_dangling

        expected = {
            "沈星河就读的学校叫什么名字？": "我没记过沈星河的学校。",
            "周晚宁就读的学校叫什么名字？": "我没记过周晚宁的学校。",
            "请问沈星河的学校叫啥？": "我没记过沈星河的学校。",
            "沈星河的学校的名字是什么？": "我没记过沈星河的学校。",
            "沈星河毕业于哪所学校？": "我没记过沈星河的学校。",
            "沈星河在哪所学校上学？": "我没记过沈星河的学校。",
            "沈星河的学校叫什么？": "我没记过沈星河的学校。",
            "沈星河的狗叫什么名字？": "我没记过沈星河的狗。",
            "沈星河养的狗叫啥？": "我没记过沈星河养的狗。",
            "沈星河的母亲是谁？": "我没记过沈星河的母亲。",
            "沈星河的电话是多少？": "我没记过沈星河的电话。",
            "沈星河的汽车颜色是什么？": "我没记过沈星河的汽车颜色。",
        }
        for question, answer in expected.items():
            got = fixed_refusal(question, [])
            self.assertEqual(got, answer, question)
            self.assertEqual(refusal_dangling(got), "", got)
        self.assertEqual(refusal_dangling("我没记过沈星河就读的学校叫。"), "叫")
        self.assertEqual(refusal_dangling("我记得柯小满，但没提到是男的还是女的。"), "")
        from memory_core.e2e_check import abstain_ok, invented_school, wrong_citations
        from memory_core.grounding import abstain_reply

        self.assertEqual(abstain_reply("沈星河", "沈星河在哪所学校上学？"), "我没记过沈星河的学校。")
        self.assertEqual(abstain_reply("周晚宁", "周晚宁的学校叫什么？"), "我没记过周晚宁的学校。")
        invented = "周晚宁的学校叫北京师范大学附属中学。"
        self.assertEqual(invented_school("周晚宁的学校叫什么？", invented), "中学")
        self.assertTrue(wrong_citations([
            {"q": "周晚宁的学校叫什么？", "answer": invented, "abstain": True, "kind": "never"},
        ]))
        self.assertTrue(abstain_ok(
            {"reason": "entity_grounded", "expert": None, "fired": False},
            "没有存过关于沈星河的这件事。",
            "沈星河",
        ))

    def test_wrong_cited_value_fails_the_job(self):
        from memory_core.e2e_check import wrong_citations

        missed = wrong_citations([
            {"q": "沈星河的学校叫什么？", "answer": "云朵。", "abstain": False, "kind": "never"},
        ])
        self.assertTrue(missed)
        self.assertIn("云朵", missed[0])
        clean = wrong_citations([
            {"q": "沈星河的学校叫什么？", "answer": "我没记过沈星河的学校。", "abstain": True, "kind": "never"},
            {"q": "沈星河的猫叫什么名字？", "answer": "云朵。", "gold": "云朵", "kind": "primary"},
        ])
        self.assertEqual(clean, [])


if __name__ == "__main__":
    unittest.main()

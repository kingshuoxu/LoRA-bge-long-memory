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
        self.assertIn("不在记忆里", school[0])
        self.assertNotIn("豆青", school[0])
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


if __name__ == "__main__":
    unittest.main()

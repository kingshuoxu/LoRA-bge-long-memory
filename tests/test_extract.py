import json
import unittest
from pathlib import Path

from memory_core.extract import (
    entailed,
    expand_training_fact,
    expert_display_name,
    fact_route,
    group_facts,
    merge_route_facts,
    pattern_extract,
    pronoun_only_label,
    refresh_stored_fact,
    uncovered_claims,
    visible_display_name,
)
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
        mixed = pattern_extract("Nadia Pell's car is sage green.")[0]
        self.assertEqual(mixed["attr"], "car color")
        self.assertEqual(mixed["value"], "sage green")
        copper = pattern_extract("Nadia Pell's car is copper.")[0]
        self.assertEqual(copper["attr"], "car color")
        self.assertEqual(copper["value"], "copper")
        leading = pattern_extract("Ida Voss's car is amber mist.")[0]
        self.assertEqual(leading["attr"], "car color")
        self.assertEqual(leading["value"], "amber mist")

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
        self.assertEqual(fact["entity"], "咪咪")
        self.assertEqual(fact["attr"], "宠物")
        self.assertEqual(fact["value"], "咪咪")
        dog = pattern_extract("我的狗狗叫豆包")[0]
        self.assertEqual(dog["entity"], "豆包")
        self.assertEqual(dog["attr"], "宠物")
        mother = pattern_extract("我的妈妈叫兰兰")[0]
        self.assertEqual(mother["entity"], "兰兰")
        self.assertEqual(mother["attr"], "妈妈")
        self.assertEqual(mother["value"], "兰兰")
        cat = pattern_extract("我的猫叫咪咪")[0]
        self.assertEqual(cat["entity"], "咪咪")
        self.assertEqual(cat["attr"], "宠物")
        self.assertEqual(cat["value"], "咪咪")
        self.assertEqual(fact_route(cat), "咪咪")
        self.assertEqual(expert_display_name([cat]), "咪咪")
        self.assertEqual(expert_display_name([fact, dog]), "咪咪、豆包")
        self.assertTrue(pronoun_only_label("我"))
        self.assertTrue(pronoun_only_label("I"))
        self.assertFalse(pronoun_only_label("沈星河"))
        named = pattern_extract("沈星河的猫叫暮雪")[0]
        self.assertEqual(named["entity"], "沈星河")
        self.assertEqual(fact_route(named), "沈星河")
        self.assertEqual(expert_display_name([named]), "沈星河")
        self.assertEqual(visible_display_name("咪咪", [cat]), "咪咪")
        named_self = pattern_extract("我叫徐金朔")[0]
        self.assertEqual(named_self["entity"], "我")
        self.assertEqual(named_self["value"], "徐金朔")
        self.assertEqual(fact_route(named_self), "self")
        self.assertEqual(expert_display_name([named_self]), "关于你")
        greeted = pattern_extract("你好，我是徐金朔")[0]
        self.assertEqual(greeted["statement"], "我是徐金朔。")
        self.assertEqual(greeted["entity"], "我")
        self.assertEqual(greeted["value"], "徐金朔")
        self.assertEqual(visible_display_name("沈星河", [named]), "沈星河")
        mine = pattern_extract("My cat is called Mimi.")[0]
        self.assertEqual(mine["entity"], "I")
        self.assertEqual(fact_route(mine), "self")
        self.assertEqual(expert_display_name([mine]), "关于你")
        home = pattern_extract("我住在新加坡")[0]
        org = pattern_extract("星禾科技的总部在苏州")[0]
        self.assertEqual(fact_route(home), "self")
        self.assertEqual(home["entity"], "我")
        self.assertIn("新加坡", home["value"])
        self.assertEqual(fact_route(org), "星禾科技")
        self.assertNotEqual(org["value"], "星禾科技")
        self.assertEqual([key for key, _items in group_facts([home, org, cat])], ["self", "星禾科技", "咪咪"])
        self.assertEqual(expert_display_name([home, cat]), "关于你、咪咪")
        self.assertEqual(expert_display_name([home, org]), "关于你、星禾科技")
        self.assertIn("咪咪", expert_display_name([cat]))
        self.assertNotIn("咪咪", expert_display_name([home]))
        self.assertNotIn("新加坡", expert_display_name([home]))
        self.assertNotEqual(expert_display_name([named]), named["value"])
        self.assertEqual(fact_route({"entity": "", "attr": "事实", "value": "苏州"}), "")
        self.assertEqual(group_facts([{"entity": "", "attr": "事实", "value": "苏州"}, home]), [("self", [home])])
        merged = merge_route_facts(
            [{"entity": "我", "attr": "住址", "value": "新加坡", "statement": "我住在新加坡。"}],
            [cat],
        )
        self.assertEqual(len(merged), 2)
        self.assertEqual({item["value"] for item in merged}, {"新加坡", "咪咪"})
        self.assertEqual(len(merge_route_facts(merged, [dict(cat)])), 2)
        later = pattern_extract("我住在新加坡")[0]
        self.assertEqual(fact_route(later), "self")
        self.assertNotEqual(fact_route(later), fact_route(cat))
        self.assertEqual(expert_display_name(merge_route_facts([cat], [later])), "关于你、咪咪")

    def test_general_frames_cover_company_and_paragraph(self):
        zh = "\n".join([
            "星禾科技成立于2011年。",
            "星禾科技的总部在苏州。",
            "星禾科技的创始人是韩亦舟。",
            "星禾科技养了一只狗叫栗子。",
            "星禾科技的员工人数是三百人。",
        ])
        values = {fact["value"] for fact in pattern_extract(zh)}
        self.assertTrue({"2011年", "苏州", "韩亦舟", "栗子", "三百人"} <= values, values)
        dog = next(fact for fact in pattern_extract(zh) if fact["value"] == "栗子")
        self.assertEqual(dog["entity"], "星禾科技")
        self.assertEqual(dog["attr"], "狗的名字")
        en = (
            "Brightwater Labs was founded in 1998. It is based in Halden. "
            "Its founder is Iris Moreau. Its main product is a solar water purifier. "
            "The office cat is called Pickle. It has 450 employees."
        )
        en_facts = pattern_extract(en)
        en_values = {fact["value"] for fact in en_facts}
        self.assertTrue({"1998", "Halden", "Iris Moreau", "solar water purifier", "Pickle", "450"} <= en_values, en_values)
        self.assertTrue(all(fact["entity"] == "Brightwater Labs" for fact in en_facts), en_facts)
        self.assertEqual(pattern_extract("Theodora Quill works as a marine biologist.")[0]["value"], "marine biologist")
        self.assertEqual(pattern_extract("Theodora Quill plays the oboe.")[0]["value"], "oboe")
        for fact in pattern_extract(zh) + pattern_extract(en):
            self.assertTrue(entailed(fact, zh + "\n" + en) or entailed(fact, zh) or entailed(fact, en))

    def test_first_person_english_and_color_ack_shape(self):
        mine = pattern_extract("My favorite color is blue.")[0]
        self.assertEqual(mine["entity"], "I")
        self.assertIn("blue", mine["value"].lower())
        swapped = pattern_extract("Blue is my favorite color.")[0]
        self.assertEqual(swapped["entity"], "I")
        self.assertEqual(swapped["value"].lower(), "blue")

    def test_hallucinated_value_dropped(self):
        self.assertFalse(entailed({"entity": "沈星河", "value": "不存在的取值"}, "沈星河的猫的名字是云朵。"))

    def test_comma_name_possessive_and_color_frames(self):
        dog = pattern_extract("北窗茶舍养了一只狗，名字叫阿黄。")[0]
        self.assertEqual(dog["entity"], "北窗茶舍")
        self.assertEqual(dog["attr"], "狗的名字")
        self.assertEqual(dog["value"], "阿黄")
        flagship = pattern_extract("Northwind Press' flagship product is linen notebooks.")[0]
        self.assertEqual(flagship["entity"], "Northwind Press")
        self.assertEqual(flagship["attr"], "flagship product")
        self.assertEqual(flagship["value"], "linen notebooks")
        cat = pattern_extract("Northwind Press has an office cat named Miso.")[0]
        self.assertEqual(cat["entity"], "Northwind Press")
        self.assertEqual(cat["attr"], "office cat's name")
        self.assertEqual(cat["value"], "Miso")
        car = pattern_extract("周衡的汽车是珍珠白的。")[0]
        self.assertEqual(car["attr"], "汽车颜色")
        self.assertEqual(car["value"], "珍珠白的")
        self.assertEqual(pattern_extract("周衡的汽车是酒红。")[0]["attr"], "汽车颜色")

    def test_partial_sentence_stays_uncovered_for_manual_add(self):
        sentence = "北窗茶舍养了一只狗，名字叫阿黄。"
        weak = [{"entity": "北窗茶舍", "value": "狗", "statement": "北窗茶舍养了一只狗。"}]
        missing = uncovered_claims(sentence, weak)
        self.assertTrue(any("阿黄" in item for item in missing), missing)
        covered = uncovered_claims(sentence, [{"entity": "北窗茶舍", "value": "阿黄", "statement": sentence}])
        self.assertEqual(covered, [])
        ui = Path(__file__).resolve().parents[1] / "desktop" / "ui"
        app = (ui / "app.js").read_text(encoding="utf-8")
        self.assertIn("preview.uncovered", app)
        self.assertIn("data-add-manual", app)
        self.assertIn("fact.uncovered", (ui / "i18n.js").read_text(encoding="utf-8"))

    def test_old_statement_gains_the_property(self):
        refreshed = refresh_stored_fact({
            "entity": "周衡",
            "attr": "鹦鹉",
            "value": "小翠",
            "statement": "周衡的鹦鹉叫小翠。",
        })
        self.assertEqual(refreshed["entity"], "周衡")
        self.assertEqual(refreshed["attr"], "鹦鹉的名字")
        self.assertEqual(refreshed["value"], "小翠")
        kept = refresh_stored_fact({
            "entity": "塔佐巴洛",
            "attr": "事实",
            "value": "1978",
            "statement": "塔佐巴洛公司成立于1978年。",
        })
        self.assertEqual(kept["entity"], "塔佐巴洛")
        self.assertIn("1978", kept["value"])
        from memory_core.correct import reissue_training_fact

        shifted = reissue_training_fact(
            {"entity": "Ida Voss", "attr": "car color", "value": "blue", "answer": "blue", "statement": "Ida Voss's car is blue."},
            "haze",
        )
        self.assertEqual(shifted["attr"], "car color")
        self.assertEqual(shifted["value"], "haze")
        chinese = reissue_training_fact(
            {"entity": "周衡", "attr": "汽车颜色", "value": "珍珠白", "answer": "珍珠白", "statement": "周衡的汽车是珍珠白的。"},
            "雾岚",
        )
        self.assertEqual(chinese["attr"], "汽车颜色")
        self.assertEqual(chinese["value"], "雾岚")
        job = reissue_training_fact(
            {"entity": "Ida Voss", "attr": "job", "value": "printmaker", "answer": "printmaker", "statement": "Ida Voss works as a printmaker."},
            "glassblower",
        )
        self.assertEqual(job["attr"], "job")


class TeachAndRecallTests(unittest.TestCase):
    def test_reported_why_is_not_quarantined(self):
        from memory_core.extract import is_question_fragment

        for sentence in ("李四问过我为什么天是蓝的", "李四说他不知道为什么下雨"):
            self.assertFalse(is_question_fragment(sentence), sentence)
        self.assertTrue(is_question_fragment("沈星河的学校叫什么"))
        self.assertTrue(is_question_fragment("柯小满是男的还是女的"))

    def test_one_message_keeps_every_declarative(self):
        text = (
            "沈星河的猫叫云朵。"
            "沈星河住在杭州。"
            "沈星河每天骑自行车。"
            "沈星河喜欢喝龙井茶。"
            "周晚宁是沈星河的同事。"
            "沈星河在青藤中学上学。"
        )
        facts = pattern_extract(text)
        values = {fact["value"] for fact in facts}
        self.assertIn("云朵", values)
        self.assertIn("杭州", values)
        self.assertIn("骑自行车", values)
        self.assertIn("龙井茶", values)
        self.assertIn("周晚宁", values)
        self.assertIn("青藤中学", values)
        colleague = next(fact for fact in facts if fact.get("attr") == "同事")
        self.assertEqual(colleague["entity"], "沈星河")
        self.assertEqual(colleague["value"], "周晚宁")
        self.assertTrue(all("什么" not in fact["statement"] for fact in facts))
        for question in (
            "磨这座灯塔透镜的工匠是诺丁。夜里值守的那位是谁？",
            "诺丁是磨镜的那位。值班的那位是谁？",
            "沈星河的猫叫云朵。沈星河的学校叫什么？",
        ):
            kept = pattern_extract(question)
            self.assertTrue(kept, question)
            self.assertFalse(any("谁" in str(fact.get("value") or "") or "什么" in str(fact.get("statement") or "") for fact in kept), question)
        taught = pattern_extract("沈星河在青藤中学上学。你知道吗？")
        self.assertEqual([fact["value"] for fact in taught], ["青藤中学"])
        from memory_core.extract import is_question_fragment

        reported = pattern_extract("李四问过我沈星河住在哪里")
        self.assertTrue(reported)
        self.assertNotEqual(reported[0]["value"], "哪里")
        self.assertFalse(is_question_fragment("她说她不知道为什么天会下雨"))
        self.assertTrue(is_question_fragment("沈星河住在哪里"))
        self.assertTrue(is_question_fragment("推荐几本书"))
        from memory_core.job_recover import finalize_dead_job

        dead = finalize_dead_job({"status": "running", "worker_pid": None, "message": "正在训练"})
        self.assertEqual(dead["status"], "failed")
        stopped = finalize_dead_job({"status": "running", "cancel_requested": True}, cancel_requested=True)
        self.assertEqual(stopped["status"], "cancelled")
        self.assertNotEqual(stopped["message"], "正在停止，当前这一小步结束后可以继续")
        for statement in (
            "沈星河就读于青藤中学",
            "沈星河毕业于青藤中学",
            "沈星河是青藤中学的学生",
            "沈星河在青藤中学读书",
            "沈星河在青藤中学念书",
        ):
            got = pattern_extract(statement)
            self.assertTrue(got and got[0]["value"] == "青藤中学", statement)

    def test_taught_school_is_not_a_false_miss(self):
        from memory_core.fact_reader import assert_school_is_recalled, read_memory
        from memory_core.span_guard import fixed_refusal

        assert_school_is_recalled()
        self.assertEqual(fixed_refusal("沈星河的学校你知道吗？", []), "我没记过沈星河的学校。")
        self.assertEqual(fixed_refusal("沈星河上的什么学校？", []), "我没记过沈星河的学校。")
        self.assertEqual(fixed_refusal("沈星河是在哪个学校读书的？", []), "我没记过沈星河的学校。")
        self.assertNotIn("你知道", fixed_refusal("会弹钢琴你知道吗？", []))
        cat_fact = {"entity": "周乔", "statement": "周乔的猫叫米粒。", "value": "米粒"}
        phone_fact = {"entity": "周乔", "statement": "周乔的电话是13800001111。", "value": "13800001111"}
        wrong_phone = (read_memory("周乔的电话是多少？", [cat_fact], None) or {}).get("text") or ""
        self.assertNotIn("米粒", wrong_phone)
        self.assertIn("13800001111", (read_memory("周乔的电话是多少？", [cat_fact, phone_fact], None) or {}).get("text") or "")
        wife = (read_memory("周乔的妻子是谁？", [cat_fact, phone_fact], None) or {}).get("text") or ""
        self.assertNotIn("米粒", wife)
        self.assertNotIn("13800001111", wife)
        gull = {"entity": "阿哨", "statement": "柯小满养了一只三条腿的海鸥，名叫阿哨。", "value": "阿哨", "source": "document"}
        refusal = fixed_refusal("那只三条腿海鸥叫什么名字？", [gull])
        self.assertFalse(refusal.startswith("我记得只三条腿") or refusal.startswith("我记得三条"), refusal)
        answer = (read_memory("那只三条腿海鸥叫什么名字？", [gull], None) or {}).get("text") or ""
        self.assertIn("阿哨", answer)
        self.assertNotIn("只三条腿", answer)
        cat = {"entity": "云朵", "statement": "她养的那只猫的名字是云朵。", "value": "云朵"}
        named = (read_memory("她养的那只猫叫什么名字？", [cat], None) or {}).get("text") or ""
        self.assertIn("云朵", named)
        self.assertNotIn("没记过", named)

    def test_chat_keeps_facts_before_tag_question_and_drops_bare_requests(self):
        from memory_core.extract import is_imperative_request, is_question_fragment, pattern_extract
        from memory_core.span_guard import asks_memory_chain, fixed_refusal

        taught = [
            "我家养了一只狗，叫胡椒。你知道吗？",
            "我会修钟表。你知道吗",
            "周晚宁是沈星河的妹妹。你知道吗？",
            "沈星河的猫叫云朵，你知道吗？",
        ]
        for text in taught:
            values = {fact["value"] for fact in pattern_extract(text)}
            self.assertTrue(values, text)
        self.assertIn("胡椒", {fact["value"] for fact in pattern_extract(taught[0])})
        self.assertIn("修钟表", {fact["value"] for fact in pattern_extract(taught[1])})
        self.assertIn("周晚宁", {fact["value"] for fact in pattern_extract(taught[2])})
        self.assertIn("云朵", {fact["value"] for fact in pattern_extract(taught[3])})
        for kept in (
            "我的职业是翻译",
            "我是一名翻译",
            "我是翻译，还是作家",
            "她喜欢别人推荐的书",
            "李四问过我为什么天是蓝的",
        ):
            self.assertFalse(is_question_fragment(kept), kept)
            self.assertFalse(is_imperative_request(kept), kept)
        for junk in (
            "帮我写一张留给邻居的留言",
            "写张留言条",
            "白鹭塔有多高",
            "告诉我谁守护白鹭塔",
        ):
            self.assertTrue(is_question_fragment(junk) or is_imperative_request(junk), junk)
            self.assertEqual(pattern_extract(junk), [], junk)
        piano = fixed_refusal("会弹钢琴你知道吗？", [])
        self.assertNotIn("会弹钢琴不在记忆里", piano)
        self.assertNotIn("你知道", piano)
        reported = fixed_refusal("李四问过我为什么天是蓝的？", [])
        self.assertNotIn("问过我为什么", reported)
        self.assertTrue(asks_memory_chain("诺丁打磨透镜的那座塔是谁守护的？"))


if __name__ == "__main__":
    unittest.main()

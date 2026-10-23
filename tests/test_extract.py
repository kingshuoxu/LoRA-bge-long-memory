import json
import unittest
from pathlib import Path

from memory_core.extract import entailed, expand_training_fact, pattern_extract, refresh_stored_fact, uncovered_claims
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


if __name__ == "__main__":
    unittest.main()

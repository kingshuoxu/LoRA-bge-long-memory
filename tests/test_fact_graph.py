"""新的一组人和事物。每一跳都必须有边，属性种类也不能借。"""
import json
import tempfile
import unittest
from pathlib import Path

from memory_core.extract import is_imperative_request, is_question_fragment, pattern_extract
from memory_core.fact_reader import read_memory
from memory_core.migrate_0214 import migrate_0214_junk
from memory_core.span_guard import fixed_refusal, memory_attribute_question


def _fact(entity: str, statement: str, value: str = "") -> dict:
    return {"entity": entity, "statement": statement, "value": value or statement, "source": "chat"}


FACTS = [
    _fact("江晚", "江晚的女儿是江小满。", "江小满"),
    _fact("江小满", "江小满养了一只猫，名叫团团。", "团团"),
    _fact("江晚", "江晚在南埠印社上班。", "南埠印社"),
    _fact("江衡", "江衡在北湾茶庄上班。", "北湾茶庄"),
    _fact("南埠印社", "南埠印社建于1912年。", "1912年"),
    _fact("江晚", "江晚看守的阁楼名叫听雨阁。", "听雨阁"),
    _fact("江小满", "江小满的自行车品牌是飞鸽。", "飞鸽"),
    _fact("江小满", "江小满的自行车是天青色。", "天青色"),
    _fact("江晚", "江晚死于1988年。", "1988年"),
]


def _answer(question: str, facts: list[dict] | None = None) -> str:
    hit = read_memory(question, facts if facts is not None else FACTS, None) or {}
    return hit.get("text") or ""


class FactGraphTests(unittest.TestCase):
    def test_each_hop_must_connect_those_two(self):
        self.assertIn("江小满", _answer("江晚的女儿叫什么？"))
        missed_son = _answer("江晚的儿子是谁？")
        self.assertNotIn("团团", missed_son)
        self.assertNotIn("江小满", missed_son)
        self.assertTrue("没记过" in missed_son or "不在记忆里" in missed_son or "没提到" in missed_son)
        self.assertIn("团团", _answer("江晚的女儿养的猫叫什么？"))
        self.assertIn("南埠印社", _answer("江小满的父亲在哪里上班？"))
        self.assertNotIn("南埠印社", _answer("江小满在哪里上班？"))
        self.assertNotIn("北湾茶庄", _answer("江小满在哪里上班？"))
        self.assertNotIn("南埠印社", _answer("江衡的父亲在哪里上班？"))
        self.assertIn("听雨阁", _answer("江小满的父亲看守的阁楼叫什么？"))
        self.assertNotIn("听雨阁", _answer("江衡的父亲看守的阁楼叫什么？"))
        self.assertIn("江晚", _answer("听雨阁的看守人叫什么？"))
        self.assertNotIn("江晚", _answer("江衡的灯夫叫什么？"))
        employer = _answer("江晚的雇主是谁？")
        self.assertNotIn("南埠印社", employer)
        self.assertNotIn("听雨阁", employer)
        self.assertTrue("没记过" in employer or "不在记忆里" in employer or "没提到" in employer)
        self.assertNotIn("南埠印社", _answer("江小满的父亲是谁？"))

    def test_year_and_object_attribute_stay_on_their_own_edge(self):
        self.assertIn("1912", _answer("南埠印社建于哪一年？"))
        demolished = _answer("南埠印社哪年拆掉？")
        self.assertNotIn("1912", demolished)
        self.assertNotIn("1988", demolished)
        self.assertIn("1988", _answer("江晚哪年去世？"))
        self.assertNotIn("1912", _answer("江晚哪年去世？"))
        brand = _answer("江小满的自行车是什么牌子？")
        self.assertIn("飞鸽", brand)
        self.assertNotIn("天青", brand)
        self.assertIn("天青", _answer("江小满的自行车是什么颜色？"))
        self.assertNotIn("飞鸽", _answer("江小满的自行车是什么颜色？"))

    def test_supported_choice_answers_and_is_not_stored(self):
        self.assertIn("天青", _answer("江小满的自行车是天青色还是墨黑？"))
        self.assertNotIn("飞鸽", _answer("江小满的自行车是天青色还是墨黑"))
        missed = _answer("江小满的自行车是飞鸽还是永久")
        self.assertIn("飞鸽", missed)
        neither = _answer("江小满的自行车是永久还是凤凰")
        self.assertNotIn("飞鸽", neither)
        self.assertNotIn("天青", neither)
        for text in (
            "江小满的自行车是天青色还是墨黑",
            "江小满的自行车是天青色还是墨黑？",
            "我的车是黑色还是墨绿",
            "他的车是黑色还是墨绿？",
        ):
            self.assertEqual(pattern_extract(text), [], text)
            self.assertTrue(is_question_fragment(text), text)

    def test_opener_and_polite_request(self):
        taught = pattern_extract("跟你说，江小满的猫叫团团。你知道吗？")
        self.assertEqual(taught[0]["value"], "团团")
        self.assertNotIn("跟你说", taught[0]["entity"])
        workplace = pattern_extract("告诉你，江晚在南埠印社上班。你知道吗？")
        self.assertEqual(workplace[0]["value"], "南埠印社")
        mixed = pattern_extract("江小满的猫叫团团。团团的主人是谁？")
        self.assertEqual([item["value"] for item in mixed], ["团团"])
        self.assertEqual(fixed_refusal("江晚在南埠印社上班。江衡的雇主是谁？", FACTS), "这件事不在记忆里。")
        self.assertTrue(memory_attribute_question("青岚草是哪里出产的植物？"))
        self.assertTrue(memory_attribute_question("青岚草产自哪里？"))
        self.assertFalse(memory_attribute_question("法国的首都是哪里？"))
        self.assertFalse(memory_attribute_question("水的化学式是什么？"))
        self.assertFalse(memory_attribute_question("帮我写一首短诗"))
        for text in ("你能不能帮我写一张便条给江晚，说我晚点到", "能不能帮我写一首短诗"):
            self.assertTrue(is_imperative_request(text), text)
            self.assertEqual(pattern_extract(text), [], text)
        refusal = fixed_refusal("夜里值守的那位叫什么？", FACTS)
        self.assertNotIn("那位", refusal)
        self.assertIn("这件事不在记忆里", refusal)
        self.assertEqual(fixed_refusal("江晚住在哪里？", FACTS).count("住不在"), 0)

    def test_lighthouse_chain_answers_the_asked_role(self):
        rows = [
            _fact("白鹭塔", "柯岚在雾港守护的第一座灯塔名叫白鹭塔，建于1873年，塔高四十二米。", "白鹭塔"),
            _fact("星砂盐", "雾港的特产是一种蓝色海盐，名叫星砂盐，每年霜降那天开始晾晒。", "星砂盐"),
            _fact("阿哨", "柯岚的女儿柯小满养了一只三条腿的海鸥，名叫阿哨。", "阿哨"),
            _fact("诺丁", "1931年白鹭塔的灯改用电灯，透镜由瑞典工匠诺丁打磨，一共有十六面。", "诺丁"),
        ]
        daughter = _answer("诺丁打磨透镜的那座塔，守护它的人的闺女叫什么？", rows)
        self.assertNotIn("柯岚", daughter)
        self.assertTrue(daughter == "这件事不在记忆里。" or "柯小满" in daughter)
        tower = _answer("晒星砂盐的那个地方，最早的灯塔叫什么？", rows)
        self.assertNotIn("星砂盐", tower)
        self.assertTrue(tower == "这件事不在记忆里。" or "白鹭塔" in tower)
        duty = _answer("诺丁负责磨。照应的那位是谁？", rows)
        self.assertNotIn("诺丁", duty)
        self.assertTrue(duty == "这件事不在记忆里。" or "柯岚" in duty)
        maker = _answer("海鸥主人她父亲负责看守的灯塔上，磨那套镜片的师傅叫什么？", rows)
        self.assertNotIn("白鹭塔", maker)
        self.assertTrue(maker == "这件事不在记忆里。" or "诺丁" in maker)
        named = _answer("小满她父亲看着的灯塔，名字叫什么？", rows)
        self.assertNotIn("柯岚", named)
        self.assertTrue(named == "这件事不在记忆里。" or "白鹭塔" in named)
        self.assertEqual(pattern_extract("磨这座灯塔透镜的工匠是诺丁。夜里值守的那位是谁？"), [])
        self.assertEqual(pattern_extract("诺丁是磨镜的那位。值班的那位是谁？"), [])
        refused = _answer("白鹭塔的闺女叫什么？", rows) + _answer("白鹭塔哪年拆除？", rows)
        self.assertIn("这件事不在记忆里", refused)

    def test_failed_hop_does_not_borrow_another_value(self):
        other = _answer("江衡养的猫叫什么？")
        self.assertNotIn("团团", other)
        self.assertEqual(other, "这件事不在记忆里。")
        dog = _answer("江晚的女儿养的狗叫什么？")
        self.assertNotIn("团团", dog)
        self.assertNotIn("江小满", dog)
        self.assertEqual(dog, "这件事不在记忆里。")
        keeper = _answer("江衡的灯夫叫什么？")
        self.assertNotIn("江晚", keeper)
        self.assertEqual(keeper, "这件事不在记忆里。")
        near = _answer("江晚川的女儿叫什么？")
        self.assertNotIn("江小满", near)
        self.assertEqual(near, "这件事不在记忆里。")
        started = _answer("南埠印社哪一年开始？")
        self.assertNotIn("1912", started)
        self.assertEqual(started, "这件事不在记忆里。")
        nation_facts = FACTS + [_fact("江晚", "江晚是南埠人，女儿是江小满。", "南埠")]
        nation = _answer("江晚是哪国人？", nation_facts)
        self.assertIn("南埠", nation)
        self.assertNotIn("江小满", nation)
        chain = _answer("江晚的女儿的父亲叫什么？")
        self.assertIn("江晚", chain)
        self.assertNotIn("团团", chain)
        self.assertEqual(fixed_refusal("夜里值守的那位叫什么？", FACTS), "这件事不在记忆里。")
        self.assertIsNone(read_memory("法国的首都是哪里？", FACTS, None))
        unknown = _answer("青岚草是什么牌子？")
        self.assertEqual(unknown, "这件事不在记忆里。")
        self.assertIn("天青", _answer("江小满的自行车是天青色还是墨黑？"))
        taught = pattern_extract("江晚的猫叫团团，团团的主人是谁？")
        self.assertEqual(taught[0]["value"], "团团")
        period = pattern_extract("江晚的猫叫团团。团团的主人是谁？")
        self.assertEqual(period[0]["value"], "团团")
        from memory_core.fact_reader import answer_stated_question
        from memory_core.world_facts import world_reply

        for mixed in ("江衡的猫叫小黑。小黑的主人是谁？", "江衡的猫叫小黑，小黑的主人是谁？"):
            stored = pattern_extract(mixed)
            self.assertTrue(stored and stored[0]["value"] == "小黑", mixed)
            reply = answer_stated_question(mixed, FACTS + stored) or {}
            self.assertIn("江衡", reply.get("text") or "", mixed)
            self.assertFalse(reply.get("miss"), mixed)
        self.assertIn("天青", _answer("自行车是天青色还是墨黑？"))
        self.assertIn("团团", _answer("江小满养的猫是团团还是小黑？"))
        self.assertEqual(_answer("江小满养的猫是小黑还是大黑？"), "这件事不在记忆里。")
        self.assertEqual(world_reply("法国的首都是哪里？", []), "巴黎。")
        self.assertEqual(world_reply("中国的首都是哪里？", []), "北京。")
        self.assertEqual(world_reply("青岚国的首都是哪里？", []), "我不知道。")
        self.assertEqual(world_reply("泽川工坊的创始人是谁？", []), "我不知道。")
        self.assertIsNone(world_reply("水的化学式是什么？", []))
        self.assertIsNone(world_reply("1加1等于几？", []))

    def test_stored_person_and_org_attributes_answer_without_borrowing(self):
        from memory_core.fact_graph import resolve_graph
        from memory_core.unseen_personas import build

        spec = build()
        facts = [
            _fact(convo["title"], sentence, sentence)
            for convo in spec["zh"]
            for sentence in convo["sentences"]
        ]
        for question, gold in spec["zh_recall"]:
            self.assertIn(gold, _answer(question, facts), question)
        for question, forbidden in spec["zh_near"]:
            self.assertNotIn(forbidden, _answer(question, facts), question)
        person = spec["zh"][0]["title"]
        flower = next(gold for _question, gold in spec["zh_recall"] if "花" in _question)
        self.assertIsNone(resolve_graph("月亮是行星还是卫星？", facts))
        self.assertNotIn(flower, _answer(f"{person}最讨厌的花是什么？", facts))
        org = spec["zh"][1]["title"]
        self.assertIsNone(resolve_graph(f"告诉我{org}相关信息", facts))
        tower = [
            _fact("白鹭塔", "柯岚在雾港守护的第一座灯塔名叫白鹭塔，建于1873年，塔高四十二米。", "白鹭塔"),
        ]
        self.assertIn("四十二", _answer("白鹭塔有多高？", tower))
        self.assertIn("1873", _answer("柯岚守护的第一座灯塔是哪年建的？", tower))
        self.assertIn("柯岚", _answer("谁守护白鹭塔？", tower))
        gull = tower + [_fact("阿哨", "柯岚的女儿柯小满养了一只三条腿的海鸥，名叫阿哨。", "阿哨")]
        raised = _answer("三条腿的海鸥是谁养的？", gull)
        self.assertIn("柯小满", raised)
        self.assertNotIn("阿哨", raised)
        self.assertIn("柯小满", _answer("阿哨是谁养的？", gull))
        book = gull + [
            _fact("星砂盐", "雾港的特产是一种蓝色海盐，名叫星砂盐，每年霜降那天开始晾晒。", "星砂盐"),
            _fact("诺丁", "1931年白鹭塔的灯改用电灯，透镜由瑞典工匠诺丁打磨，一共有十六面。", "诺丁"),
        ]
        self.assertIn("诺丁", _answer("瑞典工匠叫啥名？", book))
        self.assertIn("三", _answer("柯岚女儿养的海鸥有几条腿？", book))
        self.assertIn("白鹭塔", _answer("柯小满的父亲守的是哪座塔？", book))
        self.assertIn("蓝色", _answer("星砂盐是什么颜色？", book))
        self.assertEqual(_answer("柯岚是哪座塔？", book), "这件事不在记忆里。")
        self.assertEqual(_answer("瑞典是哪座塔？", book), "这件事不在记忆里。")
        for question in ("守塔人叫什么？", "灯塔的看守人叫什么？", "守塔的人叫什么？", "这座四十二米的灯塔是谁守的？"):
            keeper = _answer(question, book)
            self.assertIn("柯岚", keeper, question)
            self.assertNotIn("白鹭塔", keeper, question)
        made = _answer("鸟的主人的爸守的那座塔的透镜是谁磨的？", book)
        self.assertIn("诺丁", made)
        self.assertNotIn("柯岚", made)
        self.assertIn("霜降", _answer("雾港的蓝色海盐每年哪天开始晒？", book))
        daughter = _answer("打磨透镜那座塔的守护人的丫头叫什么？", book)
        self.assertIn("柯小满", daughter)
        self.assertNotIn("柯岚", daughter)
        self.assertIn("白鹭塔", _answer("霜降开始晾晒那种盐的地方，第一座灯塔叫什么？", book))
        self.assertNotIn("星砂盐", _answer("霜降开始晾晒那种盐的地方，第一座灯塔叫什么？", book))
        self.assertEqual(_answer("这座塔的透镜是诺丁磨的，负责看顾的那位叫什么？", book), "柯岚。")
        keeper_daughter = _answer("诺丁磨的透镜所在的塔，守护者的女儿叫什么？", book)
        self.assertIn("柯小满", keeper_daughter)
        self.assertNotIn("柯岚", keeper_daughter)
        self.assertEqual(_answer("养三腿海鸥的女孩，她父亲执勤的塔名叫啥？", book), "这件事不在记忆里。")

    def test_restore_junk_is_cleaned_on_next_startup(self):
        from memory_core.migrate_0214 import restore_0214_junk

        root = Path(tempfile.mkdtemp())
        home = root / "data"
        expert = home / "experts" / "expert_3"
        expert.mkdir(parents=True)
        (expert / "fact_memory.json").write_text(json.dumps({"facts": [
            {"entity": "江晚", "statement": "江晚在南埠印社上班", "value": "南埠印社", "app_version": "0.2.35"},
        ]}), encoding="utf-8")
        marker = home / "migrations"
        marker.mkdir(parents=True)
        (marker / "cleanup-0214.json").write_text(json.dumps({"done": True, "version": 4, "removed": 1}), encoding="utf-8")
        quarantine = home / "cleaned"
        quarantine.mkdir(parents=True)
        (quarantine / "0214-junk.json").write_text(json.dumps({"items": [{
            "file": "experts/expert_3/fact_memory.json",
            "fact": {"entity": "我", "statement": "能不能帮我写一首短诗", "value": "短诗", "app_version": "0.2.35"},
        }]}), encoding="utf-8")
        self.assertGreaterEqual(restore_0214_junk(home), 1)
        removed = migrate_0214_junk(home)
        self.assertGreaterEqual(removed, 1)
        left = [item["statement"] for item in json.loads((expert / "fact_memory.json").read_text(encoding="utf-8"))["facts"]]
        self.assertIn("江晚在南埠印社上班", left)
        self.assertNotIn("能不能帮我写一首短诗", left)

    def test_cleanup_reruns_when_the_classifier_changes(self):
        root = Path(tempfile.mkdtemp())
        home = root / "data"
        expert = home / "experts" / "expert_9"
        expert.mkdir(parents=True)
        facts = [
            {"entity": "江晚", "statement": "江晚在南埠印社上班", "value": "南埠印社", "app_version": "0.2.32"},
            {"entity": "我", "statement": "你能不能帮我写一张便条给江晚", "value": "便条", "app_version": "0.2.32"},
            {"entity": "我", "statement": "江小满的自行车是天青色还是墨黑", "value": "天青色还是墨黑", "app_version": "0.2.33"},
            {"entity": "我", "statement": "我是翻译，还是作家", "value": "翻译", "app_version": "0.2.32"},
        ]
        (expert / "fact_memory.json").write_text(json.dumps({"app_version": "0.2.32", "facts": facts}), encoding="utf-8")
        (home / "app-version.json").write_text(json.dumps({"version": "0.2.32"}), encoding="utf-8")
        queued = home / "documents" / "doc1"
        queued.mkdir(parents=True)
        (queued / "queued.json").write_text(json.dumps([
            "青岚书院有多高，建了多久",
            "能不能帮我写一首短诗",
            "江晚在南埠印社上班",
        ]), encoding="utf-8")
        marker = home / "migrations"
        marker.mkdir(parents=True)
        (marker / "cleanup-0214.json").write_text(json.dumps({"done": True, "removed": 0}), encoding="utf-8")
        removed = migrate_0214_junk(home)
        self.assertGreaterEqual(removed, 3)
        left = [item["statement"] for item in json.loads((expert / "fact_memory.json").read_text(encoding="utf-8"))["facts"]]
        self.assertIn("江晚在南埠印社上班", left)
        self.assertIn("我是翻译，还是作家", left)
        self.assertNotIn("你能不能帮我写一张便条给江晚", left)
        self.assertNotIn("江小满的自行车是天青色还是墨黑", left)
        pending = json.loads((queued / "queued.json").read_text(encoding="utf-8"))
        self.assertIn("江晚在南埠印社上班", pending)
        self.assertNotIn("青岚书院有多高，建了多久", pending)
        self.assertNotIn("能不能帮我写一首短诗", pending)
        self.assertEqual(migrate_0214_junk(home), 0)


if __name__ == "__main__":
    unittest.main()

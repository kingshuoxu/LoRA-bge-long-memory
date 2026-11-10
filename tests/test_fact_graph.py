"""新的一组人和事物。每一跳都必须有边，属性种类也不能借。"""
import json
import tempfile
import unittest
from pathlib import Path

from memory_core.extract import is_imperative_request, is_question_fragment, pattern_extract
from memory_core.fact_reader import read_memory
from memory_core.migrate_0214 import migrate_0214_junk
from memory_core.span_guard import fixed_refusal


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

    def test_year_and_object_attribute_stay_on_their_own_edge(self):
        self.assertIn("1912", _answer("南埠印社建于哪一年？"))
        demolished = _answer("南埠印社哪年拆除？")
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
        for text in ("你能不能帮我写一张便条给江晚，说我晚点到", "能不能帮我写一首短诗"):
            self.assertTrue(is_imperative_request(text), text)
            self.assertEqual(pattern_extract(text), [], text)
        refusal = fixed_refusal("夜里值守的那位叫什么？", FACTS)
        self.assertNotIn("那位", refusal)
        self.assertIn("这件事不在记忆里", refusal)
        self.assertEqual(fixed_refusal("江晚住在哪里？", FACTS).count("住不在"), 0)

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

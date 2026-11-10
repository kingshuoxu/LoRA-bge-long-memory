"""0.2.14 的清理不能误删含有「翻译」「推荐」的陈述句。"""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from memory_core.extract import is_question_fragment
from memory_core.migrate_0214 import migrate_0214_junk, restore_0214_junk, restore_legitimate_from_cleanup


LEGIT = [
    "我的职业是翻译",
    "我是一名翻译",
    "我是翻译，还是作家",
    "她是老师，还是画家",
    "她喜欢别人推荐的书",
    "我做产品推荐工作",
    "我喜欢写诗",
    "张三喜欢《十万个为什么》",
    "李四问过我为什么天是蓝的",
    "李四说他不知道为什么下雨",
]
JUNK = [
    "写一首关于秋天的四行小诗",
    "帮我翻译这句话",
    "给我推荐几本书",
    "柯小满平时穿布鞋还是皮鞋？",
    "柯小满是男的还是女的",
]
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "simulated_0214_facts.json"


def _home(version: str, facts: list[dict], created_at: str = "") -> Path:
    root = Path(tempfile.mkdtemp())
    home = root / "data"
    expert = home / "experts" / "expert_9"
    expert.mkdir(parents=True)
    memory = {"app_version": version, "facts": facts, "entities": ["我"]}
    if created_at:
        memory["created_at"] = created_at
    (expert / "fact_memory.json").write_text(json.dumps(memory, ensure_ascii=False), encoding="utf-8")
    (home / "app-version.json").write_text(json.dumps({"version": version}), encoding="utf-8")
    queued = home / "documents" / "doc1"
    queued.mkdir(parents=True)
    (queued / "queued.json").write_text(json.dumps(["工匠的名字", "啥名", "那个瑞典来…", "我的职业是翻译"]), encoding="utf-8")
    return home


def _facts(home: Path) -> list[str]:
    path = next((home / "experts").glob("*/fact_memory.json"))
    memory = json.loads(path.read_text(encoding="utf-8"))
    return [fact["statement"] for fact in memory["facts"]]


class Migrate0214Tests(unittest.TestCase):
    def _rows(self, statements: list[str], version: str) -> list[dict]:
        return [{"entity": "我", "statement": text, "value": text, "app_version": version} for text in statements]

    def test_legit_facts_survive_and_junk_is_quarantined_only_for_0214(self):
        home = _home("0.2.14", self._rows(LEGIT + JUNK, "0.2.14"))
        removed = migrate_0214_junk(home)
        self.assertEqual(removed, len(JUNK) + 3)
        left = _facts(home)
        for text in LEGIT:
            self.assertIn(text, left)
        for text in JUNK:
            self.assertNotIn(text, left)
        quarantine = json.loads((home / "cleaned" / "0214-junk.json").read_text(encoding="utf-8"))
        quarantined = [item["fact"]["statement"] for item in quarantine["items"] if "fact" in item]
        for text in JUNK:
            self.assertIn(text, quarantined)
        backups = list(home.glob("memory.bak-*"))
        self.assertEqual(len(backups), 1)
        self.assertTrue((backups[0] / "experts" / "expert_9" / "fact_memory.json").is_file())
        again = migrate_0214_junk(home)
        self.assertEqual(again, 0)
        self.assertEqual(len(list(home.glob("memory.bak-*"))), 1)
        self.assertEqual(restore_0214_junk(home), len(JUNK) + 3)
        restored = _facts(home)
        for text in JUNK:
            self.assertIn(text, restored)
            self.assertEqual(restored.count(text), 1)
        queued = json.loads(next((home / "documents").glob("*/queued.json")).read_text(encoding="utf-8"))
        self.assertIn("啥名", queued)
        self.assertEqual(queued.count("啥名"), 1)
        self.assertEqual(restore_0214_junk(home), 0)
        self.assertEqual(_facts(home).count("柯小满是男的还是女的"), 1)

    def test_same_facts_in_a_027_home_stay(self):
        home = _home("0.2.7", self._rows(LEGIT + JUNK, "0.2.7"), created_at="2026-09-01T00:00:00+00:00")
        removed = migrate_0214_junk(home)
        self.assertEqual(removed, 0)
        left = _facts(home)
        for text in LEGIT + JUNK:
            self.assertIn(text, left)
        self.assertFalse((home / "cleaned" / "0214-junk.json").exists())
        self.assertEqual(list(home.glob("memory.bak-*")), [])

    def test_translator_writer_is_not_a_question(self):
        self.assertFalse(is_question_fragment("我是翻译，还是作家"))
        self.assertFalse(is_question_fragment("张三喜欢《十万个为什么》"))
        self.assertFalse(is_question_fragment("我的职业是翻译"))
        self.assertFalse(is_question_fragment("她喜欢别人推荐的书"))
        self.assertTrue(is_question_fragment("柯小满平时穿布鞋还是皮鞋？"))
        self.assertTrue(is_question_fragment("柯小满是男的还是女的"))

    def test_fixture_file_is_not_rewritten(self):
        original = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
        home = _home("0.2.14", json.loads(FIXTURE.read_text(encoding="utf-8")))
        migrate_0214_junk(home)
        self.assertEqual(hashlib.sha256(FIXTURE.read_bytes()).hexdigest(), original)
        self.assertIn("我是翻译，还是作家", _facts(home))
        self.assertIn("张三喜欢《十万个为什么》", _facts(home))
        self.assertNotIn("柯小满平时穿布鞋还是皮鞋？", _facts(home))

    def test_mistaken_quarantine_is_restored_once(self):
        """模拟 0.2.28 已经用过宽的分类器清过、并且打过一次性标记。不是用户的真记忆。"""
        rows = self._rows(["我是翻译，还是作家", "柯小满平时穿布鞋还是皮鞋？"], "0.2.14")
        home = _home("0.2.14", [])
        expert = next((home / "experts").glob("*/fact_memory.json"))
        backup_dir = home / "memory.bak-20261108T000000Z" / "experts" / "expert_9"
        backup_dir.mkdir(parents=True)
        original = {"app_version": "0.2.14", "entities": ["我"], "facts": rows}
        (backup_dir / "fact_memory.json").write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
        backup_hash = hashlib.sha256((backup_dir / "fact_memory.json").read_bytes()).hexdigest()
        quarantine = home / "cleaned"
        quarantine.mkdir(parents=True)
        (quarantine / "0214-junk.json").write_text(json.dumps({
            "items": [
                {"file": "experts/expert_9/fact_memory.json", "fact": rows[0]},
                {"file": "experts/expert_9/fact_memory.json", "fact": rows[1]},
            ]
        }, ensure_ascii=False), encoding="utf-8")
        marker = home / "migrations"
        marker.mkdir(parents=True)
        (marker / "cleanup-0214.json").write_text(json.dumps({"done": True, "removed": 2}), encoding="utf-8")
        restored = restore_legitimate_from_cleanup(home)
        self.assertGreaterEqual(restored, 1)
        self.assertIn("我是翻译，还是作家", _facts(home))
        self.assertNotIn("柯小满平时穿布鞋还是皮鞋？", _facts(home))
        left = [item["fact"]["statement"] for item in json.loads((quarantine / "0214-junk.json").read_text(encoding="utf-8"))["items"]]
        self.assertIn("柯小满平时穿布鞋还是皮鞋？", left)
        self.assertNotIn("我是翻译，还是作家", left)
        self.assertEqual(hashlib.sha256((backup_dir / "fact_memory.json").read_bytes()).hexdigest(), backup_hash)
        self.assertEqual(restore_legitimate_from_cleanup(home), 0)

    def test_old_restore_marker_repairs_later_classifier(self):
        """0.2.29 已经写过恢复标记，隔离区里仍有被误清的转述。模拟数据。"""
        sentence = "李四问过我为什么天是蓝的"
        junk = "沈星河住在哪里"
        pending = "她说她不知道为什么天会下雨"
        rows = self._rows([sentence, junk], "0.2.14")
        home = _home("0.2.14", [])
        quarantine = home / "cleaned"
        quarantine.mkdir(parents=True)
        (quarantine / "0214-junk.json").write_text(json.dumps({
            "items": [
                {"file": "experts/expert_9/fact_memory.json", "fact": rows[0]},
                {"file": "experts/expert_9/fact_memory.json", "fact": rows[1]},
                {"file": "documents/doc1/queued.json", "text": pending},
            ]
        }, ensure_ascii=False), encoding="utf-8")
        marker = home / "migrations"
        marker.mkdir(parents=True)
        (marker / "restore-0214-kept.json").write_text(json.dumps({"done": True, "restored": 1}), encoding="utf-8")
        restored = restore_legitimate_from_cleanup(home)
        self.assertGreaterEqual(restored, 2)
        self.assertIn(sentence, _facts(home))
        self.assertNotIn(junk, _facts(home))
        queued = json.loads((home / "documents" / "doc1" / "queued.json").read_text(encoding="utf-8"))
        self.assertIn(pending, queued)
        self.assertEqual(restore_legitimate_from_cleanup(home), 0)
        self.assertEqual(_facts(home).count(sentence), 1)
        self.assertEqual(queued.count(pending), 1)

    def test_version_two_restore_does_not_keep_questions(self):
        question = "柯岚是守护者还是工匠？"
        polite = "能不能帮我写一张留言"
        legit = "李四问过我为什么天是蓝的"
        rows = self._rows([question, legit], "0.2.14")
        home = _home("0.2.14", [rows[0]])
        quarantine = home / "cleaned"
        quarantine.mkdir(parents=True)
        doc = home / "documents" / "doc1"
        if not doc.is_dir():
            doc.mkdir(parents=True)
        (quarantine / "0214-junk.json").write_text(json.dumps({
            "items": [
                {"file": "experts/expert_9/fact_memory.json", "fact": rows[0]},
                {"file": "experts/expert_9/fact_memory.json", "fact": rows[1]},
                {"file": "documents/doc1/queued.json", "text": polite},
            ]
        }, ensure_ascii=False), encoding="utf-8")
        (home / "documents" / "doc1" / "queued.json").write_text(json.dumps([polite]), encoding="utf-8")
        marker = home / "migrations"
        marker.mkdir(parents=True)
        (marker / "restore-0214-kept.json").write_text(json.dumps({"done": True, "version": 2, "restored": 15}), encoding="utf-8")
        restore_legitimate_from_cleanup(home)
        self.assertNotIn(question, _facts(home))
        self.assertIn(legit, _facts(home))
        queued = json.loads((home / "documents" / "doc1" / "queued.json").read_text(encoding="utf-8"))
        self.assertNotIn(polite, queued)

    def test_0215_without_backup_cannot_be_restored(self):
        """0.2.15 直接删掉含「翻译」的句子，没有备份也没有隔离。模拟数据，不是用户的真记忆。"""
        home = _home("0.2.15", self._rows(["我喜欢写诗"], "0.2.15"))
        self.assertEqual(restore_legitimate_from_cleanup(home), 0)
        self.assertEqual(_facts(home), ["我喜欢写诗"])
        self.assertFalse((home / "cleaned" / "0214-junk.json").exists())
        self.assertEqual(list(home.glob("memory.bak-*")), [])


if __name__ == "__main__":
    unittest.main()

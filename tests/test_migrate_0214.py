"""0.2.14 的清理不能误删含有「翻译」「推荐」的陈述句。"""
import json
import tempfile
import unittest
from pathlib import Path

from memory_core.migrate_0214 import migrate_0214_junk, restore_0214_junk


LEGIT = [
    "我的职业是翻译",
    "我是一名翻译",
    "她喜欢别人推荐的书",
    "我做产品推荐工作",
    "我喜欢写诗",
]
JUNK = [
    "写一首关于秋天的四行小诗",
    "帮我翻译这句话",
    "给我推荐几本书",
]


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
        self.assertEqual(removed, 3 + 3)
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
        self.assertEqual(restore_0214_junk(home), 3)
        restored = _facts(home)
        for text in JUNK:
            self.assertIn(text, restored)

    def test_same_facts_in_a_027_home_stay(self):
        home = _home("0.2.7", self._rows(LEGIT + JUNK, "0.2.7"), created_at="2026-09-01T00:00:00+00:00")
        removed = migrate_0214_junk(home)
        self.assertEqual(removed, 0)
        left = _facts(home)
        for text in LEGIT + JUNK:
            self.assertIn(text, left)
        self.assertFalse((home / "cleaned" / "0214-junk.json").exists())
        self.assertEqual(list(home.glob("memory.bak-*")), [])


if __name__ == "__main__":
    unittest.main()

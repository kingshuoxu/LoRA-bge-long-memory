"""升级时不能丢掉还留在 WAL 里的对话。"""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from memory_core.legacy_data import migrate_legacy


class LegacyWalTests(unittest.TestCase):
    def test_uncheckpointed_rows_survive_the_move(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "legacy"
            home = root / "home"
            models = root / "models"
            source.mkdir()
            home.mkdir()
            db = source / "conversations.sqlite"
            conn = sqlite3.connect(db)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA wal_autocheckpoint=0")
            conn.execute("CREATE TABLE conversations (id INTEGER PRIMARY KEY, title TEXT)")
            conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, body TEXT)")
            conn.execute("INSERT INTO conversations (title) VALUES ('kept')")
            conn.executemany("INSERT INTO messages (body) VALUES (?)", [("m",)] * 10)
            conn.commit()
            self.assertTrue((source / "conversations.sqlite-wal").is_file())
            migrate_legacy(home, models, source_home=source)
            conn.close()
            moved = sqlite3.connect(home / "conversations.sqlite")
            conversations = moved.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
            messages = moved.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            moved.close()
            self.assertEqual(conversations, 1)
            self.assertEqual(messages, 10)


if __name__ == "__main__":
    unittest.main()

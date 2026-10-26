"""旧目录只补缺，不盖住已经在新目录里的对话和模型。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from memory_core.legacy_data import migrate_legacy
from memory_core.models_mgr import models_ready


def _sparse(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.truncate(size)


class LegacyDataTests(unittest.TestCase):
    def test_missing_files_move_and_existing_files_stay(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            old_home = base / "old-home"
            old_models = base / "old-models"
            new_home = base / "new-home"
            new_models = base / "new-models"
            (old_home / "experts").mkdir(parents=True)
            (old_home / "experts" / "keep.txt").write_text("from-old", encoding="utf-8")
            (old_home / "conversations.sqlite").write_bytes(b"UPGRADE_KEEP")
            (old_home / "settings.json").write_text('{"locale": "zh-CN", "update_url": "http://m"}', encoding="utf-8")
            (new_home / "experts").mkdir(parents=True)
            (new_home / "experts" / "keep.txt").write_text("stay", encoding="utf-8")
            (new_home / "conversations.sqlite").write_bytes(b"already")
            _sparse(old_models / "Qwen2.5-0.5B-Instruct" / "model.safetensors", 500_000_000)
            _sparse(old_models / "bge-small-zh-v1.5" / "model.safetensors", 10_000_000)
            self.assertTrue(models_ready(old_models))
            with patch("memory_core.legacy_data.legacy_home", return_value=old_home), patch(
                "memory_core.legacy_data.legacy_models", return_value=old_models
            ):
                migrate_legacy(new_home, new_models)
            self.assertEqual((new_home / "conversations.sqlite").read_bytes(), b"already")
            self.assertEqual((new_home / "experts" / "keep.txt").read_text(encoding="utf-8"), "stay")
            self.assertTrue((old_home / "conversations.sqlite").is_file())
            self.assertIn("update_url", (new_home / "settings.json").read_text(encoding="utf-8"))
            self.assertFalse((old_home / "settings.json").exists())
            self.assertTrue(models_ready(new_models))
            self.assertFalse(old_models.exists())

    def test_ready_models_are_not_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            old_home = base / "old-home"
            old_models = base / "old-models"
            new_home = base / "new-home"
            new_models = base / "new-models"
            old_home.mkdir()
            _sparse(old_models / "Qwen2.5-0.5B-Instruct" / "model.safetensors", 500_000_000)
            _sparse(old_models / "bge-small-zh-v1.5" / "model.safetensors", 10_000_000)
            _sparse(new_models / "Qwen2.5-0.5B-Instruct" / "model.safetensors", 500_000_000)
            _sparse(new_models / "bge-small-zh-v1.5" / "model.safetensors", 10_000_000)
            sentinel = new_models / "sentinel.txt"
            sentinel.write_text("keep", encoding="utf-8")
            with patch("memory_core.legacy_data.legacy_home", return_value=old_home), patch(
                "memory_core.legacy_data.legacy_models", return_value=old_models
            ):
                migrate_legacy(new_home, new_models)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
            self.assertTrue(old_models.is_dir())


if __name__ == "__main__":
    unittest.main()

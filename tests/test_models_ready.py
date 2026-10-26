"""权重已经在本地时，ensure_models 不再向 Hugging Face 要文件。"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from unittest.mock import patch

from memory_core.models_mgr import ensure_models, publish_download_progress


def _sparse(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.truncate(size)


class ModelsReadyTests(unittest.TestCase):
    def test_ensure_models_does_not_download_when_weights_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _sparse(root / "Qwen2.5-0.5B-Instruct" / "model.safetensors", 500_000_000)
            _sparse(root / "bge-small-zh-v1.5" / "model.safetensors", 10_000_000)
            previous = os.environ.get("HF_HUB_OFFLINE")
            os.environ["HF_HUB_OFFLINE"] = "1"
            try:
                ensure_models(root)
            finally:
                if previous is None:
                    os.environ.pop("HF_HUB_OFFLINE", None)
                else:
                    os.environ["HF_HUB_OFFLINE"] = previous
            status = json.loads((root / "download_status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["state"], "ready")

    def test_download_progress_names_the_file_and_percent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            incomplete = root / "Qwen2.5-0.5B-Instruct" / "model.safetensors.incomplete"
            incomplete.parent.mkdir(parents=True)
            incomplete.write_bytes(b"x" * 2500)
            totals = {
                "Qwen/Qwen2.5-0.5B-Instruct": 8000,
                "BAAI/bge-small-zh-v1.5": 2000,
            }
            with patch.dict("memory_core.models_mgr._PROGRESS_TOTAL", totals, clear=True):
                status = publish_download_progress(root, "Qwen/Qwen2.5-0.5B-Instruct")
            self.assertEqual(status["state"], "downloading")
            self.assertEqual(status["file"], "model.safetensors")
            self.assertEqual(status["downloaded"], 2500)
            self.assertEqual(status["total"], 10000)
            self.assertEqual(status["percent"], 25)
            saved = json.loads((root / "download_status.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["percent"], 25)
            self.assertEqual(saved["detail"], "Qwen/Qwen2.5-0.5B-Instruct")


if __name__ == "__main__":
    unittest.main()

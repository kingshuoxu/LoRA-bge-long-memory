"""权重已经在本地时，ensure_models 不再向 Hugging Face 要文件。"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from memory_core.models_mgr import ensure_models


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


if __name__ == "__main__":
    unittest.main()

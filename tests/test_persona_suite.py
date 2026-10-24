"""调参分片之外的人。阈值改动如果只在调参的人身上好看，这里会失败。"""
import unittest
from pathlib import Path

from memory_core.persona_suite import HELD, TUNE, assert_held_out, score_split
from memory_core.routing import bind_bge

ROOT = Path(__file__).resolve().parents[1]


class PersonaSuiteTests(unittest.TestCase):
    def test_held_out_rates(self):
        weight = ROOT / "models" / "bge-small-zh-v1.5" / "model.safetensors"
        if not weight.is_file():
            self.skipTest("缺少 bge 模型")
        bind_bge(ROOT / "models")
        tune_ids = {persona["id"] for persona in TUNE}
        held_ids = {persona["id"] for persona in HELD}
        self.assertGreaterEqual(sum(1 for persona in TUNE if persona["lang"] == "zh"), 5)
        self.assertGreaterEqual(sum(1 for persona in TUNE if persona["lang"] == "en"), 5)
        self.assertTrue(tune_ids.isdisjoint(held_ids))
        assert_held_out(score_split(HELD))


if __name__ == "__main__":
    unittest.main()

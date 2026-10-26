"""保存语言时不能把更新镜像清掉。"""
import tempfile
import unittest
from pathlib import Path

from memory_core.settings import load_settings, save_settings


class SettingsTests(unittest.TestCase):
    def test_locale_save_keeps_update_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            save_settings(home, update_url="https://mirror.example/lora")
            save_settings(home, locale="en")
            data = load_settings(home)
            self.assertEqual(data["locale"], "en")
            self.assertEqual(data["update_url"], "https://mirror.example/lora")
            save_settings(home, update_url="")
            self.assertEqual(load_settings(home)["locale"], "en")
            self.assertEqual(load_settings(home)["update_url"], "")


if __name__ == "__main__":
    unittest.main()

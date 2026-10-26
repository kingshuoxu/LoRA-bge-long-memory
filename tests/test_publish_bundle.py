"""发布目录要合并两份 mac 更新描述，并跳过调试文件。"""
import importlib.util
import tempfile
import unittest
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "packaging" / "publish_desktop_release.py"
_SPEC = importlib.util.spec_from_file_location("publish_desktop_release", _PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
collect_files = _MODULE.collect_files
merge_update_info = _MODULE.merge_update_info
release_manifest = _MODULE.release_manifest


class PublishBundleTests(unittest.TestCase):
    def test_merge_keeps_both_mac_arch_files(self):
        merged = merge_update_info([
            {
                "version": "0.2.0",
                "files": [{"url": "LoRA-bge-memory-0.2.0-mac-arm64.zip", "sha512": "a", "size": 1}],
                "path": "LoRA-bge-memory-0.2.0-mac-arm64.zip",
                "sha512": "a",
            },
            {
                "version": "0.2.0",
                "files": [
                    {"url": "LoRA-bge-memory-0.2.0-mac-x64.zip", "sha512": "b", "size": 2},
                    {"url": "LoRA-bge-memory-0.2.0-mac-arm64.zip", "sha512": "a", "size": 1},
                ],
                "path": "LoRA-bge-memory-0.2.0-mac-x64.dmg",
                "sha512": "c",
            },
        ], notes="说明")
        urls = [item["url"] for item in merged["files"]]
        self.assertEqual(urls, [
            "LoRA-bge-memory-0.2.0-mac-arm64.zip",
            "LoRA-bge-memory-0.2.0-mac-x64.zip",
        ])
        self.assertTrue(str(merged["path"]).endswith(".zip"))
        self.assertEqual(merged["releaseNotes"], "说明")

    def test_manifest_lists_installers_only(self):
        manifest = release_manifest("0.2.0", "desktop-v0.2.0", "说明", [
            "LoRA-bge-memory-0.2.0-linux-amd64.deb",
            "latest-linux.yml",
            "app.AppImage.blockmap",
        ], {"LoRA-bge-memory-0.2.0-linux-amd64.deb": "abc"})
        self.assertEqual(manifest["files"], [{
            "name": "LoRA-bge-memory-0.2.0-linux-amd64.deb",
            "url": "LoRA-bge-memory-0.2.0-linux-amd64.deb",
            "sha256": "abc",
        }])

    def test_collect_skips_builder_debug(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "linux").mkdir()
            (root / "linux" / "builder-debug.yml").write_text("nope", encoding="utf-8")
            (root / "linux" / "latest-linux.yml").write_text("version: 0.2.0\n", encoding="utf-8")
            (root / "linux" / "app.AppImage").write_bytes(b"app")
            (root / "linux" / "app.AppImage.blockmap").write_bytes(b"map")
            names = {path.name for path in collect_files(root)}
            self.assertEqual(names, {"latest-linux.yml", "app.AppImage", "app.AppImage.blockmap"})


if __name__ == "__main__":
    unittest.main()

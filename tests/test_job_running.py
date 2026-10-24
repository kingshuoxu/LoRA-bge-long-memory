import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from memory_core.service import MemoryService
from memory_core.store import atomic_write_json, read_json


class JobRunningTests(unittest.TestCase):
    def test_finished_job_does_not_block_chat(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            service = MemoryService(home=home, models_dir=home / "models", device="cpu", use_repo_experts=False)
            job_id = "job_test"
            job_dir = service.jobs_dir / job_id
            job_dir.mkdir()
            atomic_write_json(service.jobs_dir / "current.json", {"id": job_id})
            proc = subprocess.Popen(["sleep", "30"])
            service._proc = proc
            try:
                atomic_write_json(job_dir / "status.json", {"id": job_id, "status": "done"})
                self.assertFalse(service.job_running())
                atomic_write_json(job_dir / "status.json", {"id": job_id, "status": "running"})
                self.assertTrue(service.job_running())
            finally:
                proc.kill()
                proc.wait()

    def test_status_write_retries_sharing_violation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "status.json"
            calls = {"n": 0}
            real = os.replace

            def flaky(src, dst):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise PermissionError(13, "Permission denied", str(dst))
                return real(src, dst)

            with patch("memory_core.store.os.replace", flaky), patch("memory_core.store.time.sleep"):
                atomic_write_json(path, {"status": "running", "epoch": 1})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"status": "running", "epoch": 1})
            self.assertEqual(calls["n"], 2)
            self.assertEqual(list(Path(tmp).glob("*.tmp")), [])

    def test_status_write_stops_after_repeated_sharing_violation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "status.json"

            def blocked(src, dst):
                raise PermissionError(13, "Permission denied", str(dst))

            with patch("memory_core.store.os.replace", blocked), patch("memory_core.store.time.sleep"):
                with self.assertRaises(PermissionError):
                    atomic_write_json(path, {"status": "running"})
            self.assertFalse(path.exists())
            self.assertEqual(list(Path(tmp).glob("*.tmp")), [])

    def test_status_read_retries_sharing_violation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "status.json"
            path.write_text('{"status": "done"}\n', encoding="utf-8")
            calls = {"n": 0}
            real = Path.read_text

            def flaky(self, encoding="utf-8", errors=None):
                if self == path:
                    calls["n"] += 1
                    if calls["n"] == 1:
                        raise PermissionError(13, "Permission denied", str(self))
                return real(self, encoding=encoding, errors=errors)

            with patch("pathlib.Path.read_text", flaky), patch("memory_core.store.time.sleep"):
                self.assertEqual(read_json(path), {"status": "done"})
            self.assertEqual(calls["n"], 2)


if __name__ == "__main__":
    unittest.main()

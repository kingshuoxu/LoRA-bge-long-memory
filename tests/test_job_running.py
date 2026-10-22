import subprocess
import tempfile
import unittest
from pathlib import Path

from memory_core.service import MemoryService
from memory_core.store import atomic_write_json


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


if __name__ == "__main__":
    unittest.main()

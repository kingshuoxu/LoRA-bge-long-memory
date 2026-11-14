import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from memory_core.service import MemoryService
from memory_core.store import atomic_write_json, read_json


class ChatIntakeTests(unittest.TestCase):
    def test_tag_question_reaches_pending_and_empty_chain_does_not_invent(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            service = MemoryService(home=home, models_dir=home / "models", device="cpu", use_repo_experts=False)
            service.chat.reply = lambda *args, **kwargs: "约翰。"
            conv = service.create_conversation()["id"]
            for text in (
                "我家养了一只狗，叫胡椒。你知道吗？",
                "我会修钟表。你知道吗",
                "周晚宁是沈星河的妹妹。你知道吗？",
                "沈星河的猫叫云朵，你知道吗？",
            ):
                service.send_message(conv, text)
            pending = " ".join(
                str(item.get("statement") or "") + str(item.get("value") or "")
                for item in service.list_pending()
            )
            for needle in ("胡椒", "修钟表", "周晚宁", "云朵"):
                self.assertIn(needle, pending, needle)
            fresh = service.create_conversation("空")["id"]
            answer = service.send_message(fresh, "诺丁打磨透镜的那座塔是谁守护的？")["assistant"]["content"]
            self.assertNotIn("约翰", answer)
            self.assertNotEqual(answer.strip().rstrip("。"), "诺丁")
            self.assertTrue("没记过" in answer or "不在记忆里" in answer, answer)


class ChatTurnTests(unittest.TestCase):
    def _service(self, home: Path) -> MemoryService:
        service = MemoryService(home=home, models_dir=home / "models", device="cpu", use_repo_experts=False)
        service.ensure_ready = lambda: None
        service.chat.ensure = lambda: None
        service.chat.reply = lambda *args, **kwargs: "基座编的。"
        service.chat.complete_base = lambda *args, **kwargs: "基座编的。"
        service.chat.sync_adapters = lambda *args, **kwargs: None
        return service

    def test_same_turn_fact_and_question_answers_through_chat(self):
        turns = (
            ("我的自行车是朱红色。什么颜色？", "朱红"),
            ("我的自行车是朱红色，什么颜色？", "朱红"),
            ("江衡的猫叫小黑。小黑的主人是谁？", "江衡"),
            ("江衡的猫叫小黑。它的主人是谁？", "江衡"),
            ("江衡的猫叫小黑，它叫什么名字？", "小黑"),
            ("江衡的猫叫小黑。它叫什么名字？", "小黑"),
            ("灯塔是白色的。什么颜色？", "白"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(Path(tmp))
            for text, gold in turns:
                conv = service.create_conversation()["id"]
                answer = service.send_message(conv, text)["assistant"]["content"]
                self.assertIn(gold, answer, text)
                self.assertNotIn("不在记忆里", answer, text)
                self.assertNotIn("基座编的", answer, text)
            conv = service.create_conversation()["id"]
            reported = service.send_message(conv, "她告诉我她住在南埠。")["assistant"]["content"]
            self.assertNotIn("不在记忆里", reported)
            self.assertNotIn("基座编的", reported)

    def test_chat_does_not_confirm_a_question_or_return_the_premise(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(Path(tmp))
            service.chat.reply = lambda *args, **kwargs: "是的，青禾社成立于1999年。"
            conv = service.create_conversation()["id"]
            unknown = service.send_message(conv, "青禾社是1999年成立的吗？")["assistant"]["content"]
            self.assertNotIn("1999", unknown)
            self.assertTrue("不在记忆里" in unknown or "我不知道" in unknown, unknown)
            service.chat.reply = lambda *args, **kwargs: "柯岚。"
            for question in (
                "柯岚是看守。谁是接班人？",
                "柯岚担任看守。接班的那位是谁？",
                "既然柯岚是看守，谁来接班？",
            ):
                answer = service.send_message(service.create_conversation()["id"], question)["assistant"]["content"]
                self.assertNotEqual(answer.strip().rstrip("。"), "柯岚", question)
            service.chat.reply = lambda *args, **kwargs: "诺丁是工匠。"
            job = service.send_message(service.create_conversation()["id"], "诺丁是干什么的？")["assistant"]["content"]
            self.assertNotIn("工匠", job)
            self.assertIn("我不知道", job)
            service.chat.reply = lambda *args, **kwargs: "水既是化合物也是元素。"
            both = service.send_message(service.create_conversation()["id"], "水是化合物还是元素？")["assistant"]["content"]
            self.assertNotIn("化合物", both)
            self.assertNotIn("元素", both)
            service.chat.reply = lambda *args, **kwargs: "月亮既是行星也是卫星。"
            moon = service.send_message(service.create_conversation()["id"], "月亮是行星还是卫星？")["assistant"]["content"]
            self.assertIn("卫星", moon)
            self.assertNotIn("行星", moon)
            year = service.send_message(
                service.create_conversation()["id"],
                "衡泽工坊成立于2008年。它是2012年成立的吗？",
            )["assistant"]["content"]
            self.assertTrue(year.startswith("不是"), year)
            self.assertIn("2008", year)
            first = service.create_conversation()["id"]
            service.send_message(first, "衡泽工坊成立于2008年。")
            service.chat.reply = lambda *args, **kwargs: "是的，成立于2012年。"
            follow = service.send_message(first, "它是2012年成立的吗？")["assistant"]["content"]
            self.assertTrue(follow.startswith("不是"), follow)
            self.assertIn("2008", follow)
            glued = service.send_message(service.create_conversation()["id"], "自行车是天青色还是墨黑？")["assistant"]["content"]
            self.assertNotIn("还墨", glued)
            self.assertTrue("不在记忆里" in glued or "我不知道" in glued or "天青" in glued, glued)


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

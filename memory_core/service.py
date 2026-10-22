"""桌面后端和命令行验收共用的服务。界面只通过这些方法碰记忆库。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from memory_core.chat import ChatEngine
from memory_core.conversations import ConversationStore
from memory_core.device import pick_device
from memory_core.extract import expand_training_fact, extract_fact_candidates
from memory_core.gate import apply_write_gate, keep_for_training
from memory_core.models_mgr import ensure_models, models_ready, qwen_path, read_status
from memory_core.paths import bundle_root, default_home, default_models_dir, default_repo_experts
from memory_core.routing import bind_bge, load_merged_gate, route_text
from memory_core.store import (
    ExpertRecord,
    add_tombstone,
    atomic_write_json,
    delete_writable_expert,
    load_experts,
    read_tombstones,
    weights_ready,
)


class ServiceError(RuntimeError):
    pass


class MemoryService:
    def __init__(
        self,
        home: Path | None = None,
        models_dir: Path | None = None,
        repo_experts: Path | None = None,
        device: str | None = None,
        use_repo_experts: bool | None = None,
    ):
        self.home = Path(home or default_home())
        self.home.mkdir(parents=True, exist_ok=True)
        self.models_dir = Path(models_dir or default_models_dir())
        self.models_dir.mkdir(parents=True, exist_ok=True)
        if use_repo_experts is None:
            use_repo_experts = repo_experts is not None or default_repo_experts() is not None
        self.repo_experts = Path(repo_experts) if repo_experts else (default_repo_experts() if use_repo_experts else None)
        if self.repo_experts is not None and not (self.repo_experts / "router.jsonl").is_file():
            self.repo_experts = None
        self.device_pref = device
        self.experts_dir = self.home / "experts"
        self.experts_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_dir = self.home / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.convos = ConversationStore(self.home / "conversations.sqlite")
        self.chat = ChatEngine(qwen_path(self.models_dir), device)
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._download_thread: threading.Thread | None = None

    def device_name(self) -> str:
        return pick_device(self.device_pref).type

    def start_model_prepare(self) -> None:
        if models_ready(self.models_dir):
            self._warmup_async()
            return
        if self._download_thread and self._download_thread.is_alive():
            return

        def _run():
            try:
                ensure_models(self.models_dir)
                if not self.job_running():
                    self._warmup()
            except Exception:
                pass

        self._download_thread = threading.Thread(target=_run, name="model-prepare", daemon=True)
        self._download_thread.start()

    def _warmup(self) -> None:
        if self.job_running():
            return
        with self._lock:
            if self.job_running():
                return
            bind_bge(self.models_dir)
            self.chat.ensure()

    def _warmup_async(self) -> None:
        if self._download_thread and self._download_thread.is_alive():
            return
        self._download_thread = threading.Thread(target=self._warmup, name="warmup", daemon=True)
        self._download_thread.start()

    def ensure_ready(self) -> None:
        ensure_models(self.models_dir)
        bind_bge(self.models_dir)

    def health(self) -> dict[str, Any]:
        status = read_status(self.models_dir)
        if models_ready(self.models_dir):
            status = {"state": "ready", "detail": ""}
        job = self.current_job()
        return {
            "ok": True,
            "device": self._safe_device(),
            "models": status,
            "training": bool(job and job.get("status") == "running"),
            "job": job,
        }

    def _safe_device(self) -> str:
        try:
            return self.device_name()
        except Exception as exc:
            return f"error:{exc}"

    def list_conversations(self) -> list[dict]:
        return self.convos.list_conversations()

    def create_conversation(self, title: str = "新对话") -> dict:
        return self.convos.create(title)

    def get_conversation(self, conv_id: str) -> dict:
        conv = self.convos.get(conv_id)
        if conv is None:
            raise ServiceError("找不到这则对话")
        conv["messages"] = self.convos.messages(conv_id)
        return conv

    def delete_conversation(self, conv_id: str) -> None:
        if self.convos.get(conv_id) is None:
            raise ServiceError("找不到这则对话")
        self.convos.delete(conv_id)

    def expert_records(self) -> list[ExpertRecord]:
        tombstones = read_tombstones(self.home)
        records: list[ExpertRecord] = []
        if self.repo_experts is not None:
            records.extend(load_experts(self.repo_experts, writable=False, tombstones=tombstones))
        records.extend(load_experts(self.experts_dir, writable=True))
        merged: dict[str, ExpertRecord] = {}
        for record in records:
            merged[record.name] = record
        return list(merged.values())

    def list_experts(self) -> list[dict]:
        return [record.public_dict() for record in self.expert_records()]

    def route_message(self, text: str):
        self.ensure_ready()
        gate_dirs = [self.experts_dir]
        if self.repo_experts is not None:
            gate_dirs.append(self.repo_experts)
        return route_text(text, self.expert_records(), load_merged_gate(gate_dirs))

    def send_message(self, conv_id: str, content: str) -> dict[str, Any]:
        content = content.strip()
        if not content:
            raise ServiceError("请输入内容")
        if len(content) > 8000:
            raise ServiceError("这句话太长了")
        if self.convos.get(conv_id) is None:
            raise ServiceError("找不到这则对话")
        if self.job_running():
            raise ServiceError("正在巩固记忆，请等训练结束再继续对话")
        self.ensure_ready()
        with self._lock:
            history = self.convos.messages(conv_id)
            title = self.convos.get(conv_id)["title"]
            user_msg = self.convos.add_message(conv_id, "user", content)
            if title in {"", "新对话"}:
                self.convos.set_title(conv_id, content[:24])
            decision = self.route_message(content)
            experts = self.expert_records()
            self.chat.sync_adapters(experts)
            if decision.fired:
                record = next((item for item in experts if item.name == decision.expert), None)
                if record is None or not weights_ready(record.directory):
                    decision.fired = False
                    decision.label = "基座"
                    decision.reason = "missing_weights"
            prior = [{"role": item["role"], "content": item["content"]} for item in history]
            prior.append({"role": "user", "content": content})
            answer = self.chat.reply(prior, decision)
            assistant = self.convos.add_message(
                conv_id,
                "assistant",
                answer,
                expert=decision.expert,
                expert_label=decision.label,
                sim=decision.sim,
                fired=decision.fired,
                reason=decision.reason,
            )
        return {"user": user_msg, "assistant": assistant, "route": decision.public_dict()}

    def preview_consolidation(self, conversation_ids: list[str]) -> dict[str, Any]:
        if not conversation_ids:
            raise ServiceError("请先选择对话")
        if self.job_running():
            raise ServiceError("正在巩固记忆，请等训练结束")
        self.ensure_ready()
        chunks = []
        sources = []
        for conv_id in conversation_ids:
            conv = self.convos.get(conv_id)
            if conv is None:
                raise ServiceError("找不到这则对话")
            text = self.convos.user_text(conv_id)
            if text.strip():
                chunks.append(text)
            sources.append({"id": conv_id, "title": conv["title"]})
        joined = "\n".join(chunks)
        with self._lock:
            self.chat.ensure()
            facts = extract_fact_candidates(joined, self.chat.model, self.chat.tok, self.chat.device)
            keys = [record.key for record in self.expert_records()]
            facts = apply_write_gate(facts, keys, self.chat.model, self.chat.tok, self.chat.device)
        cleaned = []
        for index, fact in enumerate(facts, start=1):
            cleaned.append({
                "id": f"f{index}",
                "entity": fact.get("entity", ""),
                "attr": fact.get("attr", ""),
                "value": fact.get("value", ""),
                "statement": fact.get("statement", ""),
                "question": fact.get("question", ""),
                "answer": fact.get("answer", ""),
                "gate": fact.get("gate", "write"),
                "gate_reason": fact.get("gate_reason", ""),
                "selected": bool(fact.get("selected", True)),
                "source": fact.get("source", ""),
            })
        return {"facts": cleaned, "sources": sources}

    def start_consolidation(self, conversation_ids: list[str], facts: list[dict]) -> dict[str, Any]:
        if self.job_running():
            raise ServiceError("已有训练在进行")
        selected = [fact for fact in facts if keep_for_training(fact)]
        if not selected:
            raise ServiceError("没有要写入的事实")
        expanded = []
        for fact in selected:
            item = expand_training_fact(fact)
            if not item["entity"] or not item["value"] or not item["qa"]:
                raise ServiceError("有一条事实缺少实体或取值")
            item["gate"] = str(fact.get("gate") or "")
            expanded.append(item)
        sources = []
        for conv_id in conversation_ids:
            conv = self.convos.get(conv_id)
            if conv is not None:
                sources.append({"id": conv_id, "title": conv["title"]})
        entities = []
        for fact in expanded:
            if fact["entity"] not in entities:
                entities.append(fact["entity"])
        display = "、".join(entities[:2]) + ("等" if len(entities) > 2 else "")
        job_id = time.strftime("job_%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:4]
        job_dir = self.jobs_dir / job_id
        job_dir.mkdir(parents=True)
        request = {
            "facts": expanded,
            "sources": sources,
            "display_name": display or job_id,
            "models_dir": str(self.models_dir),
            "device": self.device_pref or "auto",
            "lr": 5e-4,
            "rank": 32,
            "alpha": 64,
            "epochs": 12,
            "min_epochs": 6,
            "patience": 3,
            "target_loss": 0.05,
            "bsz": 4,
        }
        atomic_write_json(job_dir / "request.json", request)
        atomic_write_json(
            job_dir / "status.json",
            {
                "id": job_id,
                "status": "running",
                "phase": "load",
                "epoch": 0,
                "max_epochs": 12,
                "loss": None,
                "best_loss": None,
                "message": "正在启动训练",
                "expert": None,
                "error": None,
                "lr": 5e-4,
                "device": self._safe_device(),
                "dtype": "float32",
            },
        )
        atomic_write_json(self.jobs_dir / "current.json", {"id": job_id})
        with self._lock:
            self.chat.unload()
        self._spawn(job_id)
        return self.job_status(job_id)

    def _spawn(self, job_id: str) -> None:
        job_dir = self.jobs_dir / job_id
        log_handle = (job_dir / "train.log").open("a", encoding="utf-8")
        env = os.environ.copy()
        root = str(bundle_root())
        env["PYTHONPATH"] = root if not env.get("PYTHONPATH") else root + os.pathsep + env["PYTHONPATH"]
        env["PYTHONUNBUFFERED"] = "1"
        env["HF_HUB_DISABLE_TELEMETRY"] = "1"
        self._proc = subprocess.Popen(
            [sys.executable, "-m", "memory_core.train_worker", "--home", str(self.home), "--job-id", job_id],
            cwd=root,
            env=env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
        proc = self._proc

        def _watch():
            code = proc.wait()
            status_path = job_dir / "status.json"
            if not status_path.is_file():
                return
            status = json.loads(status_path.read_text(encoding="utf-8"))
            if status.get("status") == "running":
                status["status"] = "failed"
                status["error"] = f"训练进程退出（代码 {code}）。详见 train.log"
                status["message"] = "训练失败"
                atomic_write_json(status_path, status)

        threading.Thread(target=_watch, name=f"watch-{job_id}", daemon=True).start()

    def current_job(self) -> dict | None:
        pointer = self.jobs_dir / "current.json"
        if not pointer.is_file():
            return None
        try:
            job_id = json.loads(pointer.read_text(encoding="utf-8"))["id"]
        except (json.JSONDecodeError, KeyError):
            return None
        return self.job_status(job_id)

    def job_status(self, job_id: str) -> dict:
        path = self.jobs_dir / job_id / "status.json"
        if not path.is_file():
            raise ServiceError("找不到这个训练任务")
        return json.loads(path.read_text(encoding="utf-8"))

    def job_running(self) -> bool:
        """状态已经结束时不再挡住对话。进程可能还要一瞬间才退出。"""
        job = self.current_job()
        status = job.get("status") if job else None
        if status in {"done", "cancelled", "failed"}:
            return False
        if self._proc is not None and self._proc.poll() is None:
            return True
        return status == "running"

    def cancel_job(self, job_id: str) -> dict:
        job_dir = self.jobs_dir / job_id
        if not (job_dir / "status.json").is_file():
            raise ServiceError("找不到这个训练任务")
        (job_dir / "CANCEL").write_text("1", encoding="utf-8")
        status = self.job_status(job_id)
        if status.get("status") == "running":
            status["message"] = "正在停止，当前这一小步结束后可以继续"
            atomic_write_json(job_dir / "status.json", status)
        return status

    def resume_job(self, job_id: str) -> dict:
        if self.job_running():
            raise ServiceError("已有训练在进行")
        status = self.job_status(job_id)
        if status.get("status") not in {"cancelled", "failed"}:
            raise ServiceError("这个任务现在不能继续")
        flag = self.jobs_dir / job_id / "CANCEL"
        if flag.exists():
            flag.unlink()
        status["status"] = "running"
        status["error"] = None
        status["message"] = "正在继续训练"
        atomic_write_json(self.jobs_dir / job_id / "status.json", status)
        atomic_write_json(self.jobs_dir / "current.json", {"id": job_id})
        with self._lock:
            self.chat.unload()
        self._spawn(job_id)
        return self.job_status(job_id)

    def delete_expert(self, name: str) -> dict:
        records = {record.name: record for record in self.expert_records()}
        if name not in records:
            raise ServiceError("找不到这个记忆")
        record = records[name]
        if record.writable:
            delete_writable_expert(self.experts_dir, name)
        else:
            add_tombstone(self.home, name)
        with self._lock:
            self.chat.unload()
        return {"deleted": name, "display_name": record.display_name}

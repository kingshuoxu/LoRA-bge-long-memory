"""桌面后端和命令行验收共用的服务。界面只通过这些方法碰记忆库。"""
from __future__ import annotations

import json
import os
import re
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
from memory_core.correct import propose_from_records, utterance_is_question
from memory_core.grounding import (
    acknowledge_statement,
    forget_fact_hit,
    mount_memory,
    resolve_stored_reply,
    statement_trace,
)
from memory_core.mentions import load_mentions, remember_statement
from memory_core.extract import (
    company_pipeline_extract,
    entailed,
    expand_training_fact,
    uncovered_claims,
    model_extract,
    pattern_extract,
)
from memory_core.gate import apply_write_gate, keep_for_training
from memory_core.models_mgr import ensure_models, models_ready, qwen_path, read_status
from memory_core.prompts import has_cjk
from memory_core.paths import bundle_root, default_home, default_models_dir, default_repo_experts
from memory_core.routing import bind_bge, load_merged_gate, route_text, route_with_trace
from memory_core.store import (
    ExpertRecord,
    add_tombstone,
    atomic_write_json,
    delete_writable_expert,
    read_json,
    load_experts,
    next_batch_id,
    read_tombstones,
    weights_ready,
)


class ServiceError(RuntimeError):
    pass


def _short_summary(text: str) -> str:
    """问句收成「谁的什么」，不再从问句中间截断。"""
    if has_cjk(text):
        matched = re.search(r"([\u4e00-\u9fff]{2,8})的([\u4e00-\u9fff]{1,8})", text)
        if matched and any(mark in text for mark in ("什么", "吗", "哪", "谁", "？", "?", "是")):
            return f"{matched.group(1)}的{matched.group(2)}"
        return ""
    colour = re.search(
        r"what colou?r is ([A-Za-z][\w'.-]*)(?:\s+[A-Za-z][\w'.-]*)?'s\s+([A-Za-z][\w'-]*)",
        text,
        re.IGNORECASE,
    )
    if colour:
        return f"{colour.group(1)}'s {colour.group(2)} colour"
    what = re.search(
        r"what(?:'s| is) ([A-Za-z][\w'.-]*)(?:\s+[A-Za-z][\w'.-]*)?'s\s+(.+?)\??$",
        text,
        re.IGNORECASE,
    )
    if what:
        rest = what.group(2).strip(" ?.")
        if rest:
            return f"{what.group(1)}'s {rest}"
    where = re.search(r"where does ([A-Za-z][\w'.-]*)", text, re.IGNORECASE)
    if where:
        return f"Where {where.group(1)} lives"
    return ""


def _conversation_title(content: str) -> str:
    """优先用一句短摘要。兜底时英文只在词边界截断。"""
    text = " ".join(content.split())
    if not text:
        return text
    summary = _short_summary(text)
    if summary:
        return summary
    limit = 18 if has_cjk(text) else 42
    if len(text) <= limit:
        return text
    space = text.rfind(" ", 0, limit + 1)
    if space > 0:
        return text[:space]
    if not has_cjk(text):
        end = text.find(" ")
        return text if end < 0 else text[:end]
    cut = text[:limit]
    if cut and cut[-1].isascii() and cut[-1].isalnum():
        latin = len(cut)
        while latin > 0 and cut[latin - 1].isascii() and (cut[latin - 1].isalnum() or cut[latin - 1] in "'-"):
            latin -= 1
        if 0 < latin < len(cut):
            return cut[:latin].rstrip()
    return cut


def _clip_text(text: str, limit: int = 42) -> str:
    """引用基座回答时在词边界停下，不把单词切成两半。"""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    if not has_cjk(text):
        space = text.rfind(" ", 0, limit + 1)
        if space >= 8:
            return text[:space] + "…"
    cut = text[:limit]
    if cut and cut[-1].isascii() and cut[-1].isalnum():
        while cut and cut[-1].isascii() and (cut[-1].isalnum() or cut[-1] in "'-"):
            cut = cut[:-1]
        cut = cut.rstrip()
    return (cut or text[:limit].rstrip()) + "…"


def _stage_skeleton() -> list[dict[str, Any]]:
    titles = [
        ("select", "选择对话"),
        ("extract", "抽取事实"),
        ("gate", "写门"),
        ("build", "编训练样本"),
        ("train", "训练 LoRA"),
        ("recall", "回忆检查"),
        ("register", "登记专家"),
        ("done", "完成"),
    ]
    return [{"id": stage_id, "title": title, "state": "pending", "detail": "", "items": []} for stage_id, title in titles]


def _mark_stage(status: dict, stage_id: str, state: str, detail: str = "", items: list | None = None) -> None:
    for stage in status.get("stages") or []:
        if stage.get("id") == stage_id:
            stage["state"] = state
            stage["detail"] = detail
            if items is not None:
                stage["items"] = items
            return


def _stages_from_trace(events: list[dict]) -> list[dict[str, Any]]:
    stages = _stage_skeleton()
    for stage in stages:
        if stage["id"] in {"select", "extract", "gate"}:
            items = [event for event in events if event.get("stage") == stage["id"]]
            stage["state"] = "done"
            stage["items"] = items
            if stage["id"] == "select":
                stage["detail"] = f"选了 {len(items)} 则对话"
            elif stage["id"] == "extract":
                fresh = [item for item in items if not item.get("duplicate")]
                stage["detail"] = f"抽出 {len(fresh)} 条"
            else:
                kept = [item for item in items if item.get("selected")]
                stage["detail"] = f"保留 {len(kept)} 条，跳过 {len(items) - len(kept)} 条"
    return stages


def _attach_sources(fact: dict, conversations: list[dict]) -> None:
    if fact.get("source_conversations"):
        return
    raw = str(fact.get("raw") or fact.get("statement") or "")
    value = str(fact.get("value") or "")
    matched = []
    for conv in conversations:
        blob = conv.get("text") or ""
        if (value and value in blob) or (raw and raw[:12] and raw[:12] in blob):
            matched.append({"id": conv["id"], "title": conv["title"]})
    fact["source_conversations"] = matched or [{"id": conv["id"], "title": conv["title"]} for conv in conversations]


def _public_fact(fact: dict) -> dict[str, Any]:
    return {
        "id": fact.get("id") or "",
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
        "raw": fact.get("raw", ""),
        "source_conversations": fact.get("source_conversations") or [],
    }


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
        self.models_dir = Path(models_dir or default_models_dir())
        if os.environ.get("LORA_MEMORY_MIGRATE") == "1":
            from memory_core.legacy_data import migrate_legacy

            migrate_legacy(self.home, self.models_dir)
        self.home.mkdir(parents=True, exist_ok=True)
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
        self._preview_thread: threading.Thread | None = None

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

    def _ui_locale(self) -> str:
        from memory_core.settings import load_settings

        return load_settings(self.home).get("locale") or "zh-CN"

    def _err(self, zh: str, en: str) -> str:
        return en if self._ui_locale() == "en" else zh

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
        self.chat.ensure()
        return route_text(
            text,
            self.expert_records(),
            load_merged_gate(gate_dirs),
            model=self.chat.model,
            tok=self.chat.tok,
            device=self.chat.device,
        )

    def send_message(self, conv_id: str, content: str) -> dict[str, Any]:
        content = content.strip()
        if not content:
            raise ServiceError("请输入内容")
        if len(content) > 8000:
            raise ServiceError("这句话太长了")
        if self.convos.get(conv_id) is None:
            raise ServiceError("找不到这则对话")
        if self.job_running() or self._preview_running():
            raise ServiceError("正在巩固记忆，请等这一轮结束再继续对话")
        self.ensure_ready()
        with self._lock:
            history = self.convos.messages(conv_id)
            title = self.convos.get(conv_id)["title"]
            user_msg = self.convos.add_message(conv_id, "user", content)
            if title in {"", "新对话", "New chat"}:
                self.convos.set_title(conv_id, _conversation_title(content))
            self.chat.ensure()
            proposal = propose_from_records(
                content,
                self.expert_records(),
                model=self.chat.model,
                tok=self.chat.tok,
                device=self.chat.device,
            )
            if proposal is not None:
                english = self._ui_locale() == "en"
                if english:
                    note = f"Change “{proposal['old_statement']}” to “{proposal['new_statement']}”?"
                    reason_text = "This turn is confirming a correction, so no expert was mounted"
                    wording = "The correction is not saved yet. Memory was not used this turn."
                    expert_label = "Correction"
                else:
                    note = f"要把「{proposal['old_statement']}」改成「{proposal['new_statement']}」吗？"
                    reason_text = "这一轮在确认纠正，没有挂载专家"
                    wording = "纠正还没有写入。这一轮没有调用记忆。"
                    expert_label = "纠正"
                recall = {
                    "fired": False,
                    "abstain": True,
                    "mounted": False,
                    "reason": "correction_proposal",
                    "reason_text": reason_text,
                    "expert": proposal["expert"],
                    "mounted_expert": None,
                    "mounted_label": "基座",
                    "sim": proposal.get("score") or 0,
                    "thresholds": {},
                    "experts": [],
                    "fact_gate": None,
                    "matched_facts": [],
                    "wording": wording,
                }
                extra = json.dumps(
                    {"kind": "correction_proposal", "proposal": proposal, "trace": recall},
                    ensure_ascii=False,
                )
                assistant = self.convos.add_message(
                    conv_id,
                    "assistant",
                    note,
                    expert=proposal["expert"],
                    expert_label=expert_label,
                    sim=proposal.get("score"),
                    fired=False,
                    reason="correction_proposal",
                    extra=extra,
                )
                route = {
                    "fired": False,
                    "expert": proposal["expert"],
                    "sim": proposal.get("score") or 0,
                    "label": expert_label,
                    "reason": "correction_proposal",
                    "entity_pass": True,
                    "fact_pass": False,
                }
                return {"user": user_msg, "assistant": assistant, "route": route, "proposal": proposal, "recall": recall}
            if not utterance_is_question(content):
                remember_statement(self.home, content)
                stated = pattern_extract(content)
                if stated:
                    notes = [acknowledge_statement(fact) for fact in stated]
                    note = "".join(notes) if all(has_cjk(item) for item in notes) else " ".join(notes)
                    recall = statement_trace()
                    extra = json.dumps({"kind": "recall", "trace": recall}, ensure_ascii=False)
                    assistant = self.convos.add_message(
                        conv_id,
                        "assistant",
                        note,
                        expert=None,
                        expert_label="基座",
                        sim=None,
                        fired=False,
                        reason="statement_ack",
                        extra=extra,
                    )
                    route = {
                        "fired": False,
                        "expert": None,
                        "sim": 0.0,
                        "label": "基座",
                        "reason": "statement_ack",
                        "entity_pass": False,
                        "fact_pass": False,
                    }
                    return {"user": user_msg, "assistant": assistant, "route": route, "recall": recall}
            experts = self.expert_records()
            gate_dirs = [self.experts_dir]
            if self.repo_experts is not None:
                gate_dirs.append(self.repo_experts)
            decision, recall = route_with_trace(
                content,
                experts,
                load_merged_gate(gate_dirs),
                model=self.chat.model,
                tok=self.chat.tok,
                device=self.chat.device,
            )
            self.chat.sync_adapters(experts)
            fact_answer = None
            hint = ""
            grounded = False
            gate_info = recall.get("fact_gate") or {}
            resolved = resolve_stored_reply(content, experts, load_mentions(self.home))
            legacy_note = ""
            if resolved:
                fact_answer, expert, facts, reason = resolved
                use_lora = (
                    reason == "legacy_retrain"
                    and decision.fired
                    and expert is not None
                    and not getattr(expert, "explicit", True)
                    and decision.expert == getattr(expert, "name", None)
                )
                if use_lora:
                    legacy_note = fact_answer
                    fact_answer = None
                    recall["legacy_retrain"] = True
                elif expert is not None and reason not in {"entity_clarify", "legacy_retrain"}:
                    mount_memory(decision, recall, expert, facts, reason)
                    grounded = True
                else:
                    grounded = True
                    decision.fired = False
                    decision.expert = None
                    decision.label = "基座"
                    decision.reason = reason
                    recall["fired"] = False
                    recall["abstain"] = True
                    recall["mounted"] = False
                    recall["reason"] = reason
                    recall["reason_text"] = "这句话点到了提过的名字，但记忆里没有事实，所以不交给基座编"
                    recall["expert"] = None
                    recall["mounted_expert"] = None
                    recall["mounted_label"] = "基座"
                    recall["matched_facts"] = []
                    if reason == "entity_clarify":
                        forget_fact_hit(decision, recall)
            elif decision.fired and gate_info.get("answer_from_fact"):
                from memory_core.paraphrase import polar_reply_from_fact

                matched = [fact for fact in (recall.get("matched_facts") or []) if isinstance(fact, dict)]
                if matched:
                    fact_answer = polar_reply_from_fact(content, matched[0]) or str(matched[0].get("value") or "")
            if decision.fired and not grounded:
                record = next((item for item in experts if item.name == decision.expert), None)
                if record is None or not weights_ready(record.directory):
                    decision.fired = False
                    decision.label = "基座"
                    decision.reason = "missing_weights"
                    recall["fired"] = False
                    recall["abstain"] = True
                    recall["mounted"] = False
                    recall["mounted_expert"] = None
                    recall["mounted_label"] = "基座"
                    recall["reason"] = "missing_weights"
                    recall["reason_text"] = "专家权重不在，这一轮没有挂载，回答走基座"
                    recall["matched_facts"] = []
                    fact_answer = None
                    for row in recall.get("experts") or []:
                        row["chosen"] = False
            prior = [{"role": item["role"], "content": item["content"]} for item in history]
            prior.append({"role": "user", "content": content})
            answer = fact_answer if fact_answer else self.chat.reply(prior, decision, hint=hint)
            if legacy_note:
                answer = f"{answer}\n{legacy_note}"
            extra = json.dumps({"kind": "recall", "trace": recall}, ensure_ascii=False)
            assistant = self.convos.add_message(
                conv_id,
                "assistant",
                answer,
                expert=decision.expert,
                expert_label=decision.label,
                sim=decision.sim,
                fired=decision.fired,
                reason=decision.reason,
                extra=extra,
            )
        return {"user": user_msg, "assistant": assistant, "route": decision.public_dict(), "recall": recall}

    def preview_consolidation(self, conversation_ids: list[str]) -> dict[str, Any]:
        """同步抽取，给验收脚本用。界面走 start_preview，边抽边能看到。"""
        if self.job_running() or self._preview_running():
            raise ServiceError("正在巩固记忆，请等这一轮结束")
        preview_id = self._new_preview_id()
        self._init_preview(preview_id)
        self._run_preview(preview_id, conversation_ids)
        status = self.preview_status(preview_id)
        if status.get("status") != "done":
            raise ServiceError(status.get("error") or "抽取失败")
        return {
            "facts": status.get("facts") or [],
            "sources": status.get("sources") or [],
            "empty_sources": status.get("empty_sources") or [],
            "uncovered": status.get("uncovered") or [],
            "preview_id": preview_id,
            "events": status.get("events") or [],
        }

    def start_preview(self, conversation_ids: list[str]) -> dict[str, Any]:
        if not conversation_ids:
            raise ServiceError("请先选择对话")
        if self.job_running() or self._preview_running():
            raise ServiceError("正在巩固记忆，请等这一轮结束")
        preview_id = self._new_preview_id()
        self._init_preview(preview_id)
        self._preview_thread = threading.Thread(
            target=self._run_preview,
            args=(preview_id, list(conversation_ids)),
            name=f"preview-{preview_id}",
            daemon=True,
        )
        self._preview_thread.start()
        return self.preview_status(preview_id)

    def preview_status(self, preview_id: str) -> dict[str, Any]:
        path = self.home / "previews" / preview_id / "status.json"
        if not path.is_file():
            raise ServiceError("找不到这次抽取")
        return read_json(path)

    def _preview_running(self) -> bool:
        return self._preview_thread is not None and self._preview_thread.is_alive()

    def _new_preview_id(self) -> str:
        return time.strftime("preview_%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:4]

    def _init_preview(self, preview_id: str) -> None:
        atomic_write_json(
            self.home / "previews" / preview_id / "status.json",
            {
                "id": preview_id,
                "status": "running",
                "phase": "select",
                "events": [],
                "facts": [],
                "sources": [],
                "stages": _stage_skeleton(),
                "error": None,
            },
        )

    def _flush_preview(self, preview_id: str, status: dict) -> None:
        status["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        atomic_write_json(self.home / "previews" / preview_id / "status.json", status)

    def _run_preview(self, preview_id: str, conversation_ids: list[str]) -> None:
        status = self.preview_status(preview_id)
        try:
            self.ensure_ready()
            if not conversation_ids:
                raise ServiceError("请先选择对话")
            self.ensure_ready()
            conversations = []
            for conv_id in conversation_ids:
                conv = self.convos.get(conv_id)
                if conv is None:
                    raise ServiceError("找不到这则对话")
                text = self.convos.user_text(conv_id)
                conversations.append({"id": conv_id, "title": conv["title"], "text": text})
                status["events"].append({
                    "stage": "select",
                    "conversation_id": conv_id,
                    "title": conv["title"],
                    "chars": len(text),
                })
            status["sources"] = [{"id": item["id"], "title": item["title"]} for item in conversations]
            _mark_stage(status, "select", "done", detail=f"选了 {len(conversations)} 则对话", items=[e for e in status["events"] if e["stage"] == "select"])
            _mark_stage(status, "extract", "active", detail="按原句抽取")
            status["phase"] = "extract"
            self._flush_preview(preview_id, status)
            found: list[dict] = []
            seen: set[tuple[str, str]] = set()

            def _push(fact: dict, how: str) -> None:
                entity = str(fact.get("entity") or "").strip()
                value = str(fact.get("value") or "").strip()
                # 代词和「名字就是自己」不是实体事实。整段抽取时 It/它 应该已经换成上一句的主语。
                if entity.casefold() in {"it", "its", "they", "their", "he", "she", "this", "that"} or entity in {"它", "她", "他", "其"}:
                    return
                if entity.casefold() == value.casefold():
                    return
                if not entailed(fact, "\n".join(item["text"] for item in conversations)):
                    return
                key = (entity, value)
                if key in seen:
                    status["events"].append({
                        "stage": "extract",
                        "duplicate": True,
                        "statement": fact.get("statement") or "",
                        "how": how,
                    })
                    self._flush_preview(preview_id, status)
                    return
                seen.add(key)
                _attach_sources(fact, conversations)
                found.append(fact)
                status["events"].append({
                    "stage": "extract",
                    "how": how,
                    "statement": fact.get("statement") or "",
                    "entity": fact.get("entity") or "",
                    "attr": fact.get("attr") or "",
                    "value": fact.get("value") or "",
                    "question": fact.get("question") or "",
                })
                _mark_stage(status, "extract", "active", detail=f"已抽出 {len(found)} 条", items=[e for e in status["events"] if e["stage"] == "extract"])
                self._flush_preview(preview_id, status)

            for conv in conversations:
                # 整段一起抽，It / 它 / The office cat 才能沿用上一句的主语。
                for fact in pattern_extract(conv["text"]):
                    fact["source_conversations"] = [{"id": conv["id"], "title": conv["title"]}]
                    _push(fact, "pattern")
            joined = "\n".join(item["text"] for item in conversations if item["text"].strip())
            _mark_stage(status, "extract", "active", detail="正在从机构相关的句子抽取", items=[e for e in status["events"] if e["stage"] == "extract"])
            self._flush_preview(preview_id, status)
            try:
                for fact in company_pipeline_extract(joined):
                    _push(fact, "company")
            except Exception:
                pass
            with self._lock:
                self.chat.ensure()
                _mark_stage(status, "extract", "active", detail="正在用模型从整段原文抽取", items=[e for e in status["events"] if e["stage"] == "extract"])
                self._flush_preview(preview_id, status)
                try:
                    for fact in model_extract(joined, self.chat.model, self.chat.tok, self.chat.device):
                        _push(fact, "model")
                except Exception:
                    pass
                _mark_stage(status, "extract", "done", detail=f"抽出 {len(found)} 条", items=[e for e in status["events"] if e["stage"] == "extract"])
                uncovered = []
                covered_ids = set()
                for fact in found:
                    for source in fact.get("source_conversations") or []:
                        if source.get("id"):
                            covered_ids.add(source["id"])
                for conv in conversations:
                    local = [
                        fact for fact in found
                        if any(source.get("id") == conv["id"] for source in fact.get("source_conversations") or [])
                    ]
                    for sentence in uncovered_claims(conv["text"], local):
                        uncovered.append({
                            "conversation_id": conv["id"],
                            "title": conv["title"],
                            "sentence": sentence,
                        })
                status["uncovered"] = uncovered
                status["empty_sources"] = [item for item in status["sources"] if item["id"] not in covered_ids]
                if uncovered:
                    status["events"].append({
                        "stage": "extract",
                        "uncovered": True,
                        "count": len(uncovered),
                        "sentences": [item["sentence"] for item in uncovered[:8]],
                        "detail": "有陈述句没有抽成事实，可以手动补上",
                    })
                _mark_stage(status, "gate", "active", detail="对照已有记忆和基座")
                status["phase"] = "gate"
                self._flush_preview(preview_id, status)
                keys = [record.key for record in self.expert_records()]
                cleaned = []
                for index, fact in enumerate(found, start=1):
                    gated = apply_write_gate([fact], keys, self.chat.model, self.chat.tok, self.chat.device)[0]
                    if gated.get("gate") == "write" and not gated.get("gate_reason"):
                        base = str(gated.get("base_answer") or "")
                        gated["gate_reason"] = (
                            f"基座答成「{_clip_text(base)}」，和已有记忆也不重复"
                            if base
                            else "和已有记忆不重复"
                        )
                    gated["id"] = f"f{index}"
                    gated["selected"] = bool(gated.get("selected", True)) and not str(gated.get("gate") or "").startswith("skip_")
                    public = _public_fact(gated)
                    cleaned.append(public)
                    status["events"].append({
                        "stage": "gate",
                        "id": public["id"],
                        "statement": public["statement"],
                        "value": public["value"],
                        "gate": public["gate"],
                        "gate_reason": public["gate_reason"],
                        "selected": public["selected"],
                    })
                    status["facts"] = cleaned
                    kept = sum(1 for item in cleaned if item["selected"])
                    skipped = len(cleaned) - kept
                    _mark_stage(status, "gate", "active", detail=f"保留 {kept} 条，跳过 {skipped} 条", items=[e for e in status["events"] if e["stage"] == "gate"])
                    self._flush_preview(preview_id, status)
            kept = sum(1 for item in cleaned if item["selected"])
            skipped = len(cleaned) - kept
            _mark_stage(status, "gate", "done", detail=f"保留 {kept} 条，跳过 {skipped} 条", items=[e for e in status["events"] if e["stage"] == "gate"])
            status["facts"] = cleaned
            status["status"] = "done"
            status["phase"] = "review"
            self._flush_preview(preview_id, status)
        except Exception as exc:
            status["status"] = "failed"
            status["phase"] = "failed"
            status["error"] = str(exc)
            self._flush_preview(preview_id, status)

    def start_consolidation(self, conversation_ids: list[str], facts: list[dict], preview_id: str | None = None) -> dict[str, Any]:
        if self.job_running() or self._preview_running():
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
            item["id"] = fact.get("id") or ""
            item["raw"] = fact.get("raw") or ""
            item["source_conversations"] = fact.get("source_conversations") or []
            item["gate_reason"] = fact.get("gate_reason") or ""
            expanded.append(item)
        sources = []
        for conv_id in conversation_ids:
            conv = self.convos.get(conv_id)
            if conv is not None:
                sources.append({"id": conv_id, "title": conv["title"]})
        entities = []
        for item in expanded:
            if not item.get("source_conversations"):
                item["source_conversations"] = sources
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
            "empty_sources": [],
        }
        if preview_id:
            try:
                request["empty_sources"] = list(self.preview_status(preview_id).get("empty_sources") or [])
            except ServiceError:
                request["empty_sources"] = []
        atomic_write_json(job_dir / "request.json", request)
        trace_events = self._trace_events(preview_id, sources, expanded)
        stages = _stages_from_trace(trace_events)
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
                "loss_curve": [],
                "eta_seconds": None,
                "message": "正在启动训练",
                "expert": None,
                "error": None,
                "lr": 5e-4,
                "device": self._safe_device(),
                "dtype": "float32",
                "events": trace_events,
                "stages": stages,
                "kind": "consolidate",
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
            status = read_json(status_path)
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
            job_id = read_json(pointer)["id"]
        except (json.JSONDecodeError, KeyError):
            return None
        return self.job_status(job_id)

    def job_status(self, job_id: str) -> dict:
        path = self.jobs_dir / job_id / "status.json"
        if not path.is_file():
            raise ServiceError("找不到这个训练任务")
        return read_json(path)

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

    def _trace_events(self, preview_id: str | None, sources: list[dict], facts: list[dict]) -> list[dict]:
        if preview_id:
            try:
                preview = self.preview_status(preview_id)
            except ServiceError:
                preview = None
            if preview and preview.get("events"):
                return list(preview["events"])
        events: list[dict] = []
        for source in sources:
            events.append({"stage": "select", "conversation_id": source.get("id"), "title": source.get("title") or ""})
        for fact in facts:
            events.append({
                "stage": "extract",
                "statement": fact.get("statement") or "",
                "entity": fact.get("entity") or "",
                "attr": fact.get("attr") or "",
                "value": fact.get("value") or "",
            })
            events.append({
                "stage": "gate",
                "id": fact.get("id") or "",
                "statement": fact.get("statement") or "",
                "value": fact.get("value") or "",
                "gate": fact.get("gate") or "write",
                "gate_reason": fact.get("gate_reason") or "",
                "selected": True,
            })
        return events

    def propose_correction(self, text: str = "", fact_id: str | None = None, new_value: str | None = None) -> dict | None:
        self.ensure_ready()
        if fact_id and new_value:
            return propose_from_records(text, self.expert_records(), fact_id=fact_id, new_value=new_value)
        self.chat.ensure()
        return propose_from_records(
            text,
            self.expert_records(),
            fact_id=fact_id,
            new_value=new_value,
            model=self.chat.model,
            tok=self.chat.tok,
            device=self.chat.device,
        )

    def commit_correction(self, proposal: dict, conversation_id: str | None = None) -> dict[str, Any]:
        if self.job_running() or self._preview_running():
            raise ServiceError(self._err("正在巩固记忆，请等这一轮结束", "Consolidation is running. Wait for it to finish."))
        expert_name = str(proposal.get("expert") or "")
        fact_id = str(proposal.get("fact_id") or "")
        new_value = str(proposal.get("new_value") or "").strip()
        source_text = str(proposal.get("source_text") or "")
        if not expert_name or not fact_id or not new_value:
            raise ServiceError(self._err("纠正缺少事实或新取值", "The correction is missing a fact or a new value"))
        compact_value = "".join(new_value.split())
        compact_source = "".join(source_text.split())
        if compact_source and compact_value not in compact_source and compact_value.casefold() not in compact_source.casefold():
            raise ServiceError(self._err("新取值不在原来的那句话里", "The new value is not in the original sentence"))
        records = {record.name: record for record in self.expert_records()}
        record = records.get(expert_name)
        if record is None or not record.writable or not record.fact_memory:
            raise ServiceError(self._err("这条记忆不能改", "This memory cannot be edited"))
        facts = [dict(fact) for fact in record.fact_memory.get("facts") or []]
        target = None
        for index, fact in enumerate(facts):
            current_id = str(fact.get("id") or f"{record.name}#{index}")
            if current_id == fact_id:
                target = fact
                if not fact.get("id"):
                    fact["id"] = current_id
                break
        if target is None:
            raise ServiceError(self._err("找不到要改的事实", "The fact to correct was not found"))
        if target.get("superseded"):
            raise ServiceError(self._err("这条事实已经替换过了", "This fact was already replaced"))
        old_value = str(target.get("value") or target.get("answer") or "")
        if new_value == old_value:
            raise ServiceError(self._err("新取值和原来一样", "The new value is the same as the old one"))
        new_id = "c" + uuid.uuid4().hex[:8]
        target["superseded"] = True
        target["superseded_by"] = new_id
        statement = str(target.get("statement") or "")
        if old_value and old_value in statement:
            statement = statement.replace(old_value, new_value)
        elif proposal.get("new_statement"):
            statement = str(proposal["new_statement"])
        else:
            entity = str(target.get("entity") or "")
            attr = str(target.get("attr") or "")
            statement = f"{entity}的{attr}是{new_value}。" if attr else f"{entity}是{new_value}。"
        if statement and statement[-1:] not in "。！？.!?":
            statement += "。" if has_cjk(statement) else "."
        sources = list(target.get("source_conversations") or record.sources or [])
        from memory_core.correct import reissue_training_fact

        fresh = {
            "id": new_id,
            "corrects": fact_id,
            "source_conversations": sources,
            "raw": source_text,
            "selected": True,
            "gate": "write",
            "gate_reason": "用户确认后写入",
        }
        training: list[dict] = []
        memory_facts: list[dict] = []
        for fact in facts:
            if fact.get("superseded"):
                memory_facts.append(fact)
                continue
            item = expand_training_fact(fact)
            item["id"] = fact.get("id") or ""
            item["source_conversations"] = fact.get("source_conversations") or record.sources
            item["raw"] = fact.get("raw") or ""
            item["gate"] = "write"
            item["selected"] = True
            training.append(item)
            memory_facts.append(item)
        carried = dict(target)
        carried["statement"] = statement
        new_item = reissue_training_fact(carried, new_value)
        for key, value in fresh.items():
            new_item[key] = value
        training.append(new_item)
        memory_facts.append(new_item)
        if record.batch is None:
            batch = next_batch_id(self.experts_dir)
        else:
            batch = int(record.batch)
        events = [
            {"stage": "select", "title": record.display_name, "detail": "纠正一条已记住的事实"},
            {"stage": "extract", "statement": target.get("statement") or "", "value": old_value, "note": "旧事实", "superseded": True},
            {"stage": "extract", "statement": statement, "value": new_value, "note": "新事实"},
            {"stage": "gate", "statement": statement, "gate": "write", "gate_reason": "用户确认后写入", "selected": True, "value": new_value},
        ]
        job_id = time.strftime("job_%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:4]
        job_dir = self.jobs_dir / job_id
        job_dir.mkdir(parents=True)
        request = {
            "facts": training,
            "memory_facts": memory_facts,
            "sources": record.sources or sources,
            "display_name": record.display_name,
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
            "replace_name": record.name,
            "replace_batch": batch,
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
                "loss_curve": [],
                "eta_seconds": None,
                "message": "正在用纠正后的事实重新训练",
                "expert": record.name,
                "error": None,
                "lr": 5e-4,
                "device": self._safe_device(),
                "dtype": "float32",
                "events": events,
                "stages": _stages_from_trace(events),
                "kind": "correction",
            },
        )
        atomic_write_json(self.jobs_dir / "current.json", {"id": job_id})
        if conversation_id and self.convos.get(conversation_id) is not None:
            self.convos.add_message(
                conversation_id,
                "assistant",
                f"已确认。正在重新训练「{record.display_name}」，旧取值 {old_value} 会暗下去。",
                expert=record.name,
                expert_label="纠正",
                fired=False,
                reason="correction_commit",
            )
        with self._lock:
            self.chat.unload()
        self._spawn(job_id)
        return self.job_status(job_id)

    def _fact_recall_stats(self) -> tuple[dict[str, int], dict[str, str]]:
        hits: dict[str, int] = {}
        last: dict[str, str] = {}
        for conv in self.convos.list_conversations():
            for msg in self.convos.messages(conv["id"]):
                raw = msg.get("extra")
                if not raw:
                    continue
                try:
                    extra = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                trace = extra.get("trace") if isinstance(extra, dict) else None
                if not isinstance(trace, dict):
                    continue
                when = str(msg.get("created_at") or "")
                for fact in trace.get("matched_facts") or []:
                    if not isinstance(fact, dict):
                        continue
                    keys = [str(fact[key]) for key in ("node_id", "fact_id") if fact.get(key)]
                    for key in keys:
                        hits[key] = hits.get(key, 0) + 1
                        if when >= last.get(key, ""):
                            last[key] = when
        return hits, last

    def nebula(self) -> dict[str, Any]:
        self.ensure_ready()
        from memory_core.fact_span import ensure_fact_bank

        records = self.expert_records()
        experts = []
        fact_nodes = []
        links = []
        centroids = {}
        canonical: dict[str, list[str]] = {}
        for record in records:
            experts.append({
                "id": f"expert:{record.name}",
                "name": record.name,
                "display_name": record.display_name,
                "writable": record.writable,
                "explicit": record.explicit,
            })
            raw_facts: list[dict] = []
            if record.fact_memory:
                raw_facts = list(record.fact_memory.get("facts") or [])
            else:
                texts_path = record.directory / "key_texts.json"
                if texts_path.is_file():
                    texts = json.loads(texts_path.read_text(encoding="utf-8"))
                    for text in texts:
                        if isinstance(text, str) and text.endswith("。"):
                            raw_facts.append({"statement": text})
                            if len(raw_facts) >= 16:
                                break
            names: list[str] = []
            for index, fact in enumerate(raw_facts):
                fact_id = str(fact.get("id") or f"{record.name}#{index}")
                node_id = f"fact:{fact_id}"
                sources = list(fact.get("source_conversations") or record.sources or [])
                snippets = []
                for source in sources:
                    conv = self.convos.get(source.get("id", ""))
                    if conv is None:
                        continue
                    text = self.convos.user_text(conv["id"])
                    value = str(fact.get("value") or "")
                    if value and value in text:
                        at = text.find(value)
                        snippet = text[max(0, at - 36) : at + len(value) + 36]
                    else:
                        snippet = text[:180]
                    snippets.append({"id": conv["id"], "title": conv["title"], "text": snippet})
                qa = fact.get("qa") or []
                fact_nodes.append({
                    "id": node_id,
                    "fact_id": fact_id,
                    "expert": record.name,
                    "expert_label": record.display_name,
                    "statement": fact.get("statement") or "",
                    "entity": fact.get("entity") or "",
                    "attr": fact.get("attr") or "",
                    "value": fact.get("value") or fact.get("answer") or "",
                    "question": qa[0]["q"] if qa else fact.get("question") or "",
                    "superseded": bool(fact.get("superseded")),
                    "superseded_by": fact.get("superseded_by") or "",
                    "writable": record.writable and record.explicit and not fact.get("superseded"),
                    "snippets": snippets,
                })
                links.append({"source": node_id, "target": f"expert:{record.name}", "kind": "member"})
                for source in sources:
                    if source.get("id"):
                        links.append({"source": node_id, "target": f"conv:{source['id']}", "kind": "source"})
                entity = str(fact.get("entity") or "").strip()
                if entity and not fact.get("superseded") and entity not in names:
                    names.append(entity)
            if not names:
                names = [entity for entity in record.entities if 2 <= len(entity) <= 12]
            canonical[record.name] = names
            bank = ensure_fact_bank(record) if record.explicit else None
            if bank is not None and bank.question_vecs.numel():
                vec = bank.question_vecs.mean(dim=0)
            else:
                vec = record.key.float().mean(dim=0)
            norm = float(vec.norm()) or 1.0
            centroids[record.name] = vec / norm
        names_in_order = [record.name for record in records]
        for index, left in enumerate(names_in_order):
            for right in names_in_order[index + 1 :]:
                shared = [entity for entity in canonical.get(left, []) if entity in canonical.get(right, [])]
                score = float(centroids[left] @ centroids[right])
                if shared:
                    links.append({
                        "source": f"expert:{left}",
                        "target": f"expert:{right}",
                        "kind": "entity",
                        "score": round(score, 4),
                        "entities": shared,
                    })
                elif score >= 0.72:
                    links.append({
                        "source": f"expert:{left}",
                        "target": f"expert:{right}",
                        "kind": "semantic",
                        "score": round(score, 4),
                    })
        present = {item["name"] for item in experts}
        if self.repo_experts is not None and (self.repo_experts / "router.jsonl").is_file():
            from memory_core.paths import ensure_scripts_path

            ensure_scripts_path()
            from router import extract_entities_from_key_texts

            for line in (self.repo_experts / "router.jsonl").read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                entry = json.loads(line)
                name = str(entry.get("expert") or "")
                if not name or name in present:
                    continue
                directory = self.repo_experts / name
                texts_path = directory / "key_texts.json"
                texts = json.loads(texts_path.read_text(encoding="utf-8")) if texts_path.is_file() else []
                statements = [text for text in texts if isinstance(text, str) and text.endswith("。")]
                entities = extract_entities_from_key_texts([text for text in texts if isinstance(text, str)])
                shown = "、".join(entities[:2]) + ("等" if len(entities) > 2 else "") if entities else name
                experts.append({
                    "id": f"expert:{name}",
                    "name": name,
                    "display_name": shown,
                    "writable": False,
                    "explicit": False,
                })
                for index, statement in enumerate(statements[:16]):
                    node_id = f"fact:{name}#{index}"
                    fact_nodes.append({
                        "id": node_id,
                        "fact_id": f"{name}#{index}",
                        "expert": name,
                        "expert_label": shown,
                        "statement": statement,
                        "entity": "",
                        "attr": "",
                        "value": "",
                        "question": "",
                        "superseded": False,
                        "superseded_by": "",
                        "writable": False,
                        "snippets": [],
                    })
                    links.append({"source": node_id, "target": f"expert:{name}", "kind": "member"})
                present.add(name)
        recall_hits, recall_last = self._fact_recall_stats()
        for fact in fact_nodes:
            keys = [str(fact.get("id") or ""), str(fact.get("fact_id") or "")]
            fact["recall_hits"] = max((recall_hits.get(key, 0) for key in keys), default=0)
            fact["recalled_at"] = max((recall_last.get(key) or "" for key in keys), default="")
        seen_convs: list[str] = []
        conversations = []
        for link in links:
            for end in (link["source"], link["target"]):
                if not str(end).startswith("conv:"):
                    continue
                conv_id = str(end)[5:]
                if conv_id in seen_convs:
                    continue
                seen_convs.append(conv_id)
                conv = self.convos.get(conv_id)
                text = self.convos.user_text(conv_id) if conv else ""
                conversations.append({
                    "id": f"conv:{conv_id}",
                    "conversation_id": conv_id,
                    "title": conv["title"] if conv else conv_id,
                    "snippet": text[:240],
                })
        return {"experts": experts, "facts": fact_nodes, "conversations": conversations, "links": links}

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

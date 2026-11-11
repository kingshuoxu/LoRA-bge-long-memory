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
    already_remembered,
    forget_fact_hit,
    mount_memory,
    resolve_stored_reply,
    statement_trace,
)
from memory_core.same_memory import is_same_memory
from memory_core.self_query import self_ask, self_facts, self_reply
from memory_core.mentions import load_mentions, remember_statement
from memory_core.extract import (
    SELF_DISPLAY,
    SELF_ROUTE,
    company_pipeline_extract,
    entailed,
    expand_training_fact,
    expert_display_name,
    facts_are_self,
    group_facts,
    merge_route_facts,
    model_extract,
    pattern_extract,
    sole_route,
    speaker_pronoun,
    uncovered_claims,
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
        "extra_questions": list(fact.get("extra_questions") or []),
    }


_CHAPTER = re.compile(r"第[0-9０-９一二三四五六七八九十百零两]+[章节回部篇]")


def _refusal_answer(text: str) -> bool:
    return any(mark in (text or "") for mark in (
        "不在记忆里", "还不知道", "没有找到", "没有存过", "还没告诉过我",
        "没提到", "不记得", "没记过", "我不确定",
    ))


def _is_chapter(text: str) -> bool:
    return bool(_CHAPTER.search(text or ""))


def _nebula_attr(attr: str, statement: str) -> str:
    """星云上的属性不写章节名。"""
    if not _is_chapter(attr):
        return attr
    body = _CHAPTER.sub("", statement or "")
    body = re.sub(r"^[\s　，,。]+", "", body).strip().rstrip("。")
    clause = re.split(r"[，,]", body)[0].strip()
    return clause[:18] or "这条事实"


def _nebula_value(value: str, statement: str) -> str:
    if not _is_chapter(value):
        return value
    named = re.search(r"名叫([\u4e00-\u9fffA-Za-z0-9·]{1,12})", statement or "")
    if named:
        return named.group(1)
    return _nebula_attr(value, statement)


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
        from memory_core.identity import migrate_user_identity
        from memory_core.migrate_0214 import migrate_0214_junk, restore_legitimate_from_cleanup

        migrate_user_identity(self.home)
        migrate_0214_junk(self.home)
        restore_legitimate_from_cleanup(self.home)
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
        self._proc_job: str | None = None
        self._download_thread: threading.Thread | None = None
        self._preview_thread: threading.Thread | None = None
        self._reconcile_current_job()

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

    def _stored_rows(self) -> list[dict]:
        rows = []
        for record in self.expert_records():
            memory = record.fact_memory or {}
            if not isinstance(memory, dict):
                continue
            for fact in memory.get("facts") or []:
                if isinstance(fact, dict) and not fact.get("superseded"):
                    item = dict(fact)
                    item["_expert"] = record
                    rows.append(item)
        return rows

    def _remembered_match(self, fact: dict) -> dict | None:
        statement = str(fact.get("statement") or "")
        value = str(fact.get("value") or "")
        entity = str(fact.get("entity") or "")
        for stored in self._stored_rows():
            blob = str(stored.get("statement") or "")
            matched = False
            if statement and is_same_memory(statement, blob):
                matched = True
            elif entity == "我" and value and is_same_memory(f"我叫{value}", blob):
                matched = True
            elif value and is_same_memory(statement, str(stored.get("value") or "")):
                matched = True
            if not matched:
                continue
            expert = stored.get("_expert")
            directory = getattr(expert, "directory", None)
            if directory is not None:
                from memory_core.identity import repair_identity_link

                repair_identity_link(directory, value or str(stored.get("value") or ""))
            return stored
        return None

    def _ack_turn(self, conv_id: str, user_msg: dict, note: str, reason: str) -> dict[str, Any]:
        recall = statement_trace()
        recall["reason"] = reason
        if reason == "already":
            recall["reason_text"] = "这句话已经在记忆里"
        extra = json.dumps({"kind": "recall", "trace": recall}, ensure_ascii=False)
        assistant = self.convos.add_message(
            conv_id,
            "assistant",
            note,
            expert=None,
            expert_label="基座",
            sim=None,
            fired=False,
            reason=reason,
            extra=extra,
        )
        route = {
            "fired": False,
            "expert": None,
            "sim": 0.0,
            "label": "基座",
            "reason": reason,
            "entity_pass": False,
            "fact_pass": False,
        }
        return {"user": user_msg, "assistant": assistant, "route": route, "recall": recall}

    def _finish_turn(self, conv_id: str, user_msg: dict, answer: str, decision, recall: dict) -> dict[str, Any]:
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

    def _owned_reply(self, content: str, experts: list) -> tuple[str, Any, list[dict]] | None:
        if not any(mark in content for mark in ("叫", "名字", "是谁", "什么")):
            return None
        for record in experts:
            memory = record.fact_memory or {}
            for fact in memory.get("facts") or []:
                if not isinstance(fact, dict) or fact.get("superseded"):
                    continue
                statement = str(fact.get("statement") or "")
                if "猫" in content and "猫" in statement:
                    value = str(fact.get("value") or "").strip()
                    return f"你的猫叫{value}。", record, [fact]
                if "狗" in content and "狗" in statement and "我的狗" in statement:
                    value = str(fact.get("value") or "").strip()
                    return f"你的狗叫{value}。", record, [fact]
        return None

    def _covered_reply(self, content: str, experts: list) -> tuple[str, Any, list[dict]] | None:
        """整句文档事实。问句必须同时点到主体和属性，不能只因为人名相同就拿别的事实来答。"""
        from memory_core.documents import attribute_in_statement

        best = None
        best_len = 10**9
        for record in experts:
            memory = record.fact_memory or {}
            for fact in memory.get("facts") or []:
                if not isinstance(fact, dict) or fact.get("superseded"):
                    continue
                if str(fact.get("source") or "") != "document":
                    continue
                statement = str(fact.get("statement") or "")
                entity = str(fact.get("entity") or "")
                if not attribute_in_statement(content, entity, statement):
                    continue
                if len(statement) < best_len:
                    spoken = statement if statement.endswith("。") else statement + "。"
                    best = (spoken, record, fact)
                    best_len = len(statement)
        if best is None:
            return None
        return best[0], best[1], [best[2]]

    def _personal_unknown(self, content: str) -> str | None:
        """没教过的个人问题不交给基座编。常识题仍走基座。"""
        if self_ask(content) or not utterance_is_question(content):
            return None
        from memory_core.extract import is_advice_question, is_imperative_request

        if is_advice_question(content) or is_imperative_request(content):
            return None
        personal = bool(re.search(r"我的|我最喜欢|我最爱|我比较|我非常|我喜欢|我在哪|我在什么", content)) or bool(re.search(r"\bmy\b", content.casefold()))
        if re.search(r"我", content) and re.search(r"公司|上班", content) and "我们" not in content:
            personal = True
        if not personal:
            return None
        if not re.search(r"什么|谁|哪|多少|几|吗|what|who|which", content, flags=re.IGNORECASE):
            return None
        from memory_core.fact_recall import possessed_name_query

        owned = possessed_name_query(content)
        english = self._ui_locale() == "en" or not has_cjk(content)
        if owned:
            if english:
                return f"You haven't told me what your {owned} is called."
            return f"你还没告诉过我你的{owned}叫什么。"
        if english:
            return "That isn't in memory. You can tell me."
        return "这件事不在记忆里。你可以告诉我。"

    def _read_memory(self, content: str, experts: list) -> tuple[str, Any, list[dict], bool] | None:
        """bge 取句子，基座只许摘抄。和记忆无关时返回 None。"""
        from memory_core.fact_reader import read_memory
        from memory_core.fact_recall import fact_blob

        rows = []
        owners = []
        for record in experts:
            memory = record.fact_memory or {}
            for fact in memory.get("facts") or []:
                if isinstance(fact, dict) and not fact.get("superseded"):
                    rows.append(fact)
                    owners.append(record)
        if not rows:
            return None
        query_vector = None
        fact_vectors = None
        try:
            bind_bge(self.models_dir)
            from router import embed

            vectors = embed([content] + [fact_blob(fact) for fact in rows])
            query_vector = [float(value) for value in vectors[0]]
            fact_vectors = [[float(value) for value in row] for row in vectors[1:]]
        except Exception:
            query_vector = None
            fact_vectors = None

        def generate(system: str, user: str) -> str:
            return self.chat.complete_base(system, user, max_new_tokens=32)

        found = read_memory(content, rows, generate, query_vector, fact_vectors)
        if found is None:
            return None
        fact = found.get("fact")
        if found.get("miss") or fact is None:
            return found["text"], None, [], True
        try:
            owner = owners[rows.index(fact)]
        except ValueError:
            owner = None
        if owner is None:
            return found["text"], None, [], True
        return found["text"], owner, [fact], False

    def _memory_quote(self, content: str, experts: list) -> tuple[str, Any, list[dict]] | None:
        from memory_core.fact_recall import fact_blob, recall_fact, spoken_fact, touches_memory

        rows = []
        owners = []
        for record in experts:
            memory = record.fact_memory or {}
            for fact in memory.get("facts") or []:
                if isinstance(fact, dict) and not fact.get("superseded"):
                    rows.append(fact)
                    owners.append(record)
        query_vector = None
        fact_vectors = None
        if rows:
            try:
                bind_bge(self.models_dir)
                from router import embed

                vectors = embed([content] + [fact_blob(fact) for fact in rows])
                query_vector = [float(value) for value in vectors[0]]
                fact_vectors = [[float(value) for value in row] for row in vectors[1:]]
            except Exception:
                query_vector = None
                fact_vectors = None
        hit = recall_fact(content, rows, query_vector, fact_vectors)
        if hit is None:
            if touches_memory(content, rows) and utterance_is_question(content):
                return ("这件事不在记忆里。", None, [])
            return None
        spoken = spoken_fact(content, hit)
        if not spoken:
            return None
        return spoken, owners[rows.index(hit)], [hit]

    def _document_reply(self, content: str, allow_miss: bool = True) -> dict | None:
        from memory_core.documents import admit_no_passage, document_miss, load_indexed_docs, missed_document_title, search_documents

        docs = load_indexed_docs(self.home)
        if not docs:
            return None
        query_vector = None
        try:
            bind_bge(self.models_dir)
            from router import embed

            query_vector = [float(item) for item in embed([content])[0]]
        except Exception:
            query_vector = None
        found = search_documents(content, docs, query_vector)
        if found.get("ground"):
            ground = found["ground"]
            return {"answer": ground["answer"], "chips": ground.get("chips") or [], "miss": False}
        if not allow_miss or self._personal_unknown(content):
            return None
        used = any(doc.get("vectors") for doc in docs) and query_vector is not None
        if admit_no_passage(found, used_vectors=used):
            title = missed_document_title(content, docs) or str(docs[0].get("title") or "")
            return {"answer": document_miss(title, self._ui_locale() == "en"), "chips": [], "miss": True}
        return None

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
            from memory_core.extract import is_advice_question, is_imperative_request

            stated = pattern_extract(content)
            if stated and not is_imperative_request(content) and not is_advice_question(content):
                remember_statement(self.home, content)
                if not utterance_is_question(content):
                    if stated and all(self._remembered_match(fact) for fact in stated):
                        notes = [already_remembered(fact) for fact in stated]
                        note = "".join(dict.fromkeys(notes)) if all(has_cjk(item) for item in notes) else " ".join(dict.fromkeys(notes))
                        return self._ack_turn(conv_id, user_msg, note, "already")
                    notes = [acknowledge_statement(fact) for fact in stated]
                    note = "".join(notes) if all(has_cjk(item) for item in notes) else " ".join(notes)
                    return self._ack_turn(conv_id, user_msg, note, "statement_ack")
            experts = self.expert_records()
            asked = self_ask(content)
            if asked == "assistant":
                text = "I'm Yingyu. I remember what you tell me." if self._ui_locale() == "en" else "我是萤语，帮你记住你告诉我的事。"
                recall = statement_trace()
                recall["reason"] = "assistant_intro"
                recall["reason_text"] = "这是在问助手自己，不使用关于你的记忆"
                decision = route_with_trace(content, [], None)[0]
                decision.reason = "assistant_intro"
                decision.label = "基座"
                decision.fired = False
                return self._finish_turn(conv_id, user_msg, text, decision, recall)
            from memory_core.span_guard import (
                asks_memory_chain,
                fixed_refusal,
                is_open_task,
                memory_attribute_question,
            )

            open_task = is_open_task(content)
            if asks_memory_chain(content) and not open_task and not any(
                isinstance(fact, dict) and not fact.get("superseded")
                for record in experts
                for fact in ((record.fact_memory or {}).get("facts") or [])
            ):
                decision = route_with_trace(content, [], None)[0]
                decision.fired = False
                decision.reason = "memory_miss"
                decision.label = "基座"
                decision.expert = None
                recall = statement_trace()
                recall["reason"] = "memory_miss"
                recall["abstain"] = True
                recall["fired"] = False
                recall["mounted"] = False
                recall["reason_text"] = "前半句点了名字，后半句问的角色不在记忆里"
                return self._finish_turn(conv_id, user_msg, fixed_refusal(content), decision, recall)
            memory_block = ""
            if stated and utterance_is_question(content) and not asked and not open_task:
                from memory_core.fact_reader import read_memory

                rows = []
                for record in experts:
                    memory = record.fact_memory or {}
                    for fact in memory.get("facts") or []:
                        if isinstance(fact, dict) and not fact.get("superseded"):
                            rows.append(fact)
                rows.extend(stated)
                found = read_memory(content, rows, None)
                if found and not found.get("miss"):
                    decision = route_with_trace(content, [], None)[0]
                    decision.fired = False
                    decision.reason = "statement_ack"
                    recall = statement_trace()
                    recall["reason"] = "statement_ack"
                    recall["reason_text"] = "这句话里的事实刚记下，问题用的是这句和已有的记忆"
                    return self._finish_turn(conv_id, user_msg, found["text"], decision, recall)
                notes = [acknowledge_statement(fact) for fact in stated]
                note = "".join(notes) if all(has_cjk(item) for item in notes) else " ".join(notes)
                return self._ack_turn(conv_id, user_msg, note, "statement_ack")
            if utterance_is_question(content) and not asked and not open_task:
                read = self._read_memory(content, experts)
                if read is not None:
                    text, expert, facts, miss = read
                    if not miss and expert is not None:
                        decision, recall = route_with_trace(content, experts, load_merged_gate([self.experts_dir] + ([self.repo_experts] if self.repo_experts else [])))
                        mount_memory(decision, recall, expert, facts, "entity_first")
                        recall["reason_text"] = "回答是从已记住的句子里摘出来的"
                        return self._finish_turn(conv_id, user_msg, text, decision, recall)
                    memory_block = text
            if asked and asked != "assistant":
                answered = self_reply(content, experts, english=self._ui_locale() == "en")
                if answered is not None:
                    text, expert, facts = answered
                    recall = statement_trace()
                    if expert is not None:
                        decision, recall = route_with_trace(content, experts, load_merged_gate([self.experts_dir] + ([self.repo_experts] if self.repo_experts else [])))
                        mount_memory(decision, recall, expert, facts, "entity_overview" if asked == "overview" else "entity_first")
                        recall["reason_text"] = "问的是关于你，回答来自已记住的事实"
                        return self._finish_turn(conv_id, user_msg, text, decision, recall)
                    recall["reason"] = "self_empty"
                    if asked == "place":
                        recall["reason_text"] = "还没有记下你住在哪里"
                    elif self_facts(experts):
                        recall["reason_text"] = "还没有记下这件事"
                    else:
                        recall["reason_text"] = "还没有记下关于你的事实，所以不交给基座编"
                    decision = route_with_trace(content, [], None)[0]
                    decision.reason = "self_empty"
                    decision.label = "基座"
                    decision.fired = False
                    return self._finish_turn(conv_id, user_msg, text, decision, recall)
            gate_dirs = [self.experts_dir]
            if self.repo_experts is not None:
                gate_dirs.append(self.repo_experts)
            decision, recall = route_with_trace(
                content,
                [] if open_task else experts,
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
            resolved = None if open_task else resolve_stored_reply(content, experts, load_mentions(self.home))
            if resolved and resolved[3] == "entity_clarify":
                covered_now = self._covered_reply(content, experts)
                if covered_now:
                    resolved = (covered_now[0], covered_now[1], covered_now[2], "entity_first")
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
                elif reason == "entity_grounded":
                    grounded = False
                    decision.fired = False
                    decision.expert = expert.name if expert is not None else None
                    decision.reason = reason
                    recall["fired"] = False
                    recall["mounted"] = False
                    recall["abstain"] = True
                    recall["reason"] = reason
                    recall["matched_facts"] = []
                    recall["reason_text"] = "问的是已记住的人或事物，这个取值不在记忆里"
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
            if not fact_answer:
                owned = self._owned_reply(content, experts)
                if owned:
                    fact_answer, expert, facts = owned
                    mount_memory(decision, recall, expert, facts, "entity_first")
                    grounded = True
            abstain = bool(fact_answer) and "记住的是" not in fact_answer and (
                "不在记忆里" in fact_answer or fact_answer.startswith("没有存过")
            )
            covered = self._covered_reply(content, experts) if (not fact_answer or abstain) else None
            if covered:
                fact_answer, expert, facts = covered
                mount_memory(decision, recall, expert, facts, "entity_first")
                grounded = True
            def _use_document(document: dict) -> None:
                nonlocal fact_answer, grounded
                fact_answer = document["answer"]
                recall["doc_chips"] = document.get("chips") or []
                if document.get("miss"):
                    decision.fired = False
                    decision.reason = "document_miss"
                    decision.label = "基座"
                    recall["reason"] = "document_miss"
                    recall["mounted"] = False
                    recall["fired"] = False
                    recall["abstain"] = True
                    recall["reason_text"] = "文档里没有这句话"
                else:
                    decision.fired = True
                    decision.reason = "document"
                    decision.label = "文档"
                    recall["fired"] = True
                    recall["mounted"] = True
                    recall["abstain"] = False
                    recall["reason"] = "document"
                    recall["mounted_label"] = "文档"
                    recall["reason_text"] = "回答来自导入的文档"
                    grounded = True

            open_answer = (not fact_answer) or ("不在记忆里" in fact_answer and not grounded)
            if open_answer:
                document = self._document_reply(content, allow_miss=False)
                if document:
                    _use_document(document)
            open_answer = (not fact_answer) or ("不在记忆里" in fact_answer and not grounded)
            if open_answer:
                quoted = self._memory_quote(content, experts)
                if quoted:
                    fact_answer, expert, facts = quoted
                    if expert is None:
                        grounded = False
                        decision.fired = False
                        decision.expert = None
                        decision.label = "基座"
                        decision.reason = "memory_miss"
                        recall["fired"] = False
                        recall["mounted"] = False
                        recall["abstain"] = True
                        recall["reason"] = "memory_miss"
                        recall["matched_facts"] = []
                        recall["reason_text"] = "问到了已经记住的人或事物，但这件事不在记忆里"
                    else:
                        mount_memory(decision, recall, expert, facts, "entity_first")
                        recall["reason_text"] = "回答来自已记住的原句"
                        grounded = True
            if not fact_answer and not open_task:
                unknown = self._personal_unknown(content)
                if unknown:
                    fact_answer = unknown
                    decision.fired = False
                    decision.reason = "personal_unknown"
                    decision.label = "基座"
                    decision.expert = None
                    recall["reason"] = "personal_unknown"
                    recall["reason_text"] = "没记住这件事，所以不交给基座编"
                    recall["fired"] = False
                    recall["mounted"] = False
                    recall["abstain"] = True
                    recall["expert"] = None
                    recall["mounted_expert"] = None
                    recall["mounted_label"] = "基座"
                else:
                    document = self._document_reply(content, allow_miss=True)
                    if document:
                        _use_document(document)
            if (
                fact_answer
                and memory_block
                and utterance_is_question(content)
                and recall.get("reason") not in {"entity_overview", "statement_ack", "document", "personal_unknown"}
            ):
                from memory_core.fact_reader import clashes, off_topic
                from memory_core.span_guard import predicate_covered

                needle = fact_answer.strip().rstrip("。")
                host_fact = None
                host = ""
                for record in experts:
                    for fact in (record.fact_memory or {}).get("facts") or []:
                        statement = str(fact.get("statement") or "")
                        if needle and needle in statement:
                            host_fact = fact
                            host = statement
                            break
                    if host_fact is not None:
                        break
                if host_fact is not None and (
                    clashes(content, host_fact) or off_topic(content, host_fact) or not predicate_covered(content, host, host_fact)
                ):
                    fact_answer = None
                    grounded = False
            if (
                fact_answer
                and utterance_is_question(content)
                and len(fact_answer) > 18
                and recall.get("reason") not in {"entity_overview", "statement_ack", "document"}
            ):
                from memory_core.fact_recall import answer_span
                from memory_core.span_guard import accept_aligned

                short = answer_span(content, fact_answer)
                checked = accept_aligned(content, short, {"statement": fact_answer}) if short else ""
                if checked:
                    fact_answer = checked if checked[-1] in "。." else checked + "。"
            if not fact_answer and memory_block:
                fact_answer = memory_block
                decision.fired = False
                decision.expert = None
                decision.label = "基座"
                decision.reason = "memory_miss"
                recall["fired"] = False
                recall["mounted"] = False
                recall["abstain"] = True
                recall["reason"] = "memory_miss"
                recall["matched_facts"] = []
                recall["reason_text"] = "问到了已经记住的人或事物，但这件事不在记忆里"
                recall["expert"] = None
                recall["mounted_expert"] = None
                recall["mounted_label"] = "基座"
            if not fact_answer and utterance_is_question(content) and not open_task:
                from memory_core.fact_recall import touches_memory
                from memory_core.span_guard import fixed_refusal, mentions_stored

                remembered = []
                for record in experts:
                    memory = record.fact_memory or {}
                    for fact in memory.get("facts") or []:
                        if isinstance(fact, dict) and not fact.get("superseded"):
                            remembered.append(fact)
                if touches_memory(content, remembered) or mentions_stored(content, remembered):
                    fact_answer = fixed_refusal(content, remembered)
                    decision.fired = False
                    decision.expert = None
                    decision.label = "基座"
                    decision.reason = "memory_miss"
                    recall["fired"] = False
                    recall["mounted"] = False
                    recall["abstain"] = True
                    recall["reason"] = "memory_miss"
                    recall["matched_facts"] = []
                    recall["reason_text"] = "问到了已经记住的人或事物，但这件事不在记忆里"
                    recall["mounted_expert"] = None
                    recall["mounted_label"] = "基座"
            graph_locked = False
            if utterance_is_question(content) and not open_task:
                from memory_core.fact_graph import resolve_graph

                remembered = []
                for record in experts:
                    memory = record.fact_memory or {}
                    for fact in memory.get("facts") or []:
                        if isinstance(fact, dict) and not fact.get("superseded"):
                            remembered.append(fact)
                graphed = resolve_graph(content, remembered) if remembered else None
                if graphed is not None and graphed.get("status") == "answer":
                    graph_locked = True
                    span = str(graphed.get("span") or "").strip()
                    fact_answer = span if span[-1:] in "。." else span + "。"
                    owner = next(
                        (record for record in experts if graphed.get("fact") in ((record.fact_memory or {}).get("facts") or [])),
                        None,
                    )
                    if owner is not None:
                        mount_memory(decision, recall, owner, [graphed["fact"]], "entity_first")
                        recall["doc_chips"] = []
                        recall["abstain"] = False
                        recall["reason_text"] = "回答是顺着已经记下的关系走出来的"
            if utterance_is_question(content) and not open_task and not graph_locked:
                from memory_core.span_guard import relation_decision

                remembered = []
                for record in experts:
                    memory = record.fact_memory or {}
                    for fact in memory.get("facts") or []:
                        if isinstance(fact, dict) and not fact.get("superseded"):
                            remembered.append(fact)
                linked = relation_decision(content, remembered) if remembered else None
                if linked and linked.get("status") == "abstain":
                    fact_answer = linked["text"]
                    decision.fired = False
                    decision.expert = None
                    decision.label = "基座"
                    decision.reason = "memory_miss"
                    recall["fired"] = False
                    recall["mounted"] = False
                    recall["abstain"] = True
                    recall["reason"] = "memory_miss"
                    recall["matched_facts"] = []
                    recall["reason_text"] = "关系没有走完，所以不把中间的人当成答案，也不挂引用"
                    recall["expert"] = None
                    recall["mounted_expert"] = None
                    recall["mounted_label"] = "基座"
                elif linked and linked.get("status") == "answer":
                    from memory_core.answer_type import accept_span
                    from memory_core.span_guard import statement_of

                    span = str(linked["span"])
                    host = statement_of(linked.get("fact") or {})
                    if accept_span(content, span, host) and (
                        not fact_answer
                        or _refusal_answer(fact_answer)
                        or len(fact_answer) > 18
                        or not accept_span(content, fact_answer.strip().rstrip("。"), host)
                    ):
                        fact_answer = span if span[-1:] in "。." else span + "。"
                        owner = next(
                            (record for record in experts if linked["fact"] in ((record.fact_memory or {}).get("facts") or [])),
                            None,
                        )
                        if owner is not None:
                            mount_memory(decision, recall, owner, [linked["fact"]], "entity_first")
                            recall["reason_text"] = "回答是顺着已经记下的关系摘出来的"
            if utterance_is_question(content) and not open_task and not graph_locked:
                from memory_core.answer_type import accept_span, choose_typed, grounded_subjects, memory_topic, question_kind
                from memory_core.span_guard import fixed_refusal, statement_of

                remembered = []
                for record in experts:
                    memory = record.fact_memory or {}
                    for fact in memory.get("facts") or []:
                        if isinstance(fact, dict) and not fact.get("superseded"):
                            remembered.append(fact)
                picked = choose_typed(content, remembered) if remembered else None
                personal = "我的" in content or content.startswith("我")
                if (
                    not picked
                    and not fact_answer
                    and not personal
                    and question_kind(content)
                    and grounded_subjects(content, remembered)
                    and recall.get("reason") not in {"document", "document_miss", "entity_clarify", "entity_grounded"}
                ):
                    fact_answer = fixed_refusal(content, remembered)
                    decision.fired = False
                    decision.expert = None
                    decision.label = "基座"
                    decision.reason = "memory_miss"
                    recall["fired"] = False
                    recall["mounted"] = False
                    recall["abstain"] = True
                    recall["reason"] = "memory_miss"
                    recall["matched_facts"] = []
                    recall["doc_chips"] = []
                    recall["reason_text"] = "问到了已经记住的对象，但这一种取值没有写在句子里"
                if recall.get("reason") == "document" and fact_answer and picked and picked[0] in fact_answer:
                    pass
                elif picked and (
                    not fact_answer
                    or _refusal_answer(fact_answer)
                    or not accept_span(content, fact_answer.strip().rstrip("。"), statement_of(picked[1]))
                ):
                    span, fact = picked
                    fact_answer = span if span[-1:] in "。." else span + "。"
                    owner = next(
                        (record for record in experts if fact in ((record.fact_memory or {}).get("facts") or [])),
                        None,
                    )
                    if owner is not None:
                        mount_memory(decision, recall, owner, [fact], "entity_first")
                        recall["doc_chips"] = []
                        recall["reason_text"] = "回答用的是和问句种类一致的取值"
                elif (
                    fact_answer
                    and not _refusal_answer(fact_answer)
                    and question_kind(content)
                    and recall.get("reason") not in {"document", "document_miss", "entity_clarify", "entity_grounded"}
                ):
                    host = ""
                    needle = fact_answer.strip().rstrip("。")
                    for fact in remembered:
                        if needle and needle in statement_of(fact):
                            host = statement_of(fact)
                            break
                    if not accept_span(content, needle, host or fact_answer):
                        linked_names = grounded_subjects(content, remembered)
                        stored_value = any(
                            needle and (needle == str(fact.get("value") or "") or needle in statement_of(fact))
                            for fact in remembered
                        )
                        decision.fired = False
                        recall["fired"] = False
                        recall["mounted"] = False
                        recall["matched_facts"] = []
                        recall["doc_chips"] = []
                        if not linked_names and not memory_topic(content, remembered) and not stored_value:
                            fact_answer = None
                        else:
                            fact_answer = fixed_refusal(content, remembered)
                            decision.expert = None
                            decision.label = "基座"
                            decision.reason = "memory_miss"
                            recall["abstain"] = True
                            recall["reason"] = "memory_miss"
                            recall["reason_text"] = "取值种类对不上，所以不把原句当成答案，也不挂引用"
                            recall["expert"] = None
                            recall["mounted_expert"] = None
                            recall["mounted_label"] = "基座"
            if utterance_is_question(content) and not open_task and not graph_locked and recall.get("reason") not in {
                "document", "document_miss", "entity_overview", "statement_ack", "personal_unknown", "assistant_intro", "already",
            }:
                from memory_core.answer_type import accept_span, memory_topic
                from memory_core.span_guard import fixed_refusal, statement_of

                remembered = []
                for record in experts:
                    memory = record.fact_memory or {}
                    for fact in memory.get("facts") or []:
                        if isinstance(fact, dict) and not fact.get("superseded"):
                            remembered.append(fact)
                polar_answer = bool(re.match(r"^(?:是|不是|有|Yes|No)\b", (fact_answer or "").strip(), re.IGNORECASE))
                if re.search(r"是.+还是", content or "") or (re.search(r"是不是", content or "") and not polar_answer):
                    fact_answer = fixed_refusal(content, remembered)
                    decision.fired = False
                    decision.expert = None
                    decision.label = "基座"
                    decision.reason = "memory_miss"
                    recall["fired"] = False
                    recall["mounted"] = False
                    recall["abstain"] = True
                    recall["reason"] = "memory_miss"
                    recall["matched_facts"] = []
                    recall["doc_chips"] = []
                    recall["reason_text"] = "是A还是B没有写在记忆里，不选其中一边"
                    recall["expert"] = None
                    recall["mounted_expert"] = None
                    recall["mounted_label"] = "基座"
                elif memory_topic(content, remembered):
                    needle = (fact_answer or "").strip().rstrip("。")
                    host = ""
                    for fact in remembered:
                        if needle and needle in statement_of(fact):
                            host = statement_of(fact)
                            break
                    polar = bool(re.match(r"^(?:是|不是|Yes|No)\b", (fact_answer or "").strip(), re.IGNORECASE))
                    polar_ok = False
                    if polar and fact_answer and len(fact_answer) <= 40:
                        for fact in remembered:
                            statement = statement_of(fact)
                            for piece in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,16}", fact_answer):
                                if piece in statement and accept_span(content, piece, statement):
                                    polar_ok = True
                                    break
                            if polar_ok:
                                break
                    valid = bool(fact_answer) and (
                        _refusal_answer(fact_answer) or polar_ok or (host and accept_span(content, needle, host))
                    )
                    if not valid:
                        from memory_core.answer_type import choose_typed

                        picked_now = choose_typed(content, remembered)
                        if picked_now:
                            span, fact = picked_now
                            picked_host = statement_of(fact)
                            if accept_span(content, span, picked_host, allow_chain=True):
                                fact_answer = span if span[-1:] in "。." else span + "。"
                                owner = next(
                                    (record for record in experts if fact in ((record.fact_memory or {}).get("facts") or [])),
                                    None,
                                )
                                if owner is not None:
                                    mount_memory(decision, recall, owner, [fact], "entity_first")
                                    recall["doc_chips"] = []
                                    recall["abstain"] = False
                                    recall["reason_text"] = "回答用的是和问句种类一致的取值"
                                valid = True
                    if not valid:
                        fact_answer = fixed_refusal(content, remembered)
                        decision.fired = False
                        decision.expert = None
                        decision.label = "基座"
                        decision.reason = "memory_miss"
                        recall["fired"] = False
                        recall["mounted"] = False
                        recall["abstain"] = True
                        recall["reason"] = "memory_miss"
                        recall["matched_facts"] = []
                        recall["doc_chips"] = []
                        recall["reason_text"] = "问到了已经记住的人或事物，但这件事不在记忆里，所以不交给基座编"
                        recall["expert"] = None
                        recall["mounted_expert"] = None
                        recall["mounted_label"] = "基座"
            if not fact_answer and not open_task:
                from memory_core.span_guard import fixed_refusal, personal_attribute_question

                if personal_attribute_question(content) or memory_attribute_question(content):
                    fact_answer = fixed_refusal(content)
                    decision.fired = False
                    decision.expert = None
                    decision.label = "基座"
                    decision.reason = "memory_miss"
                    recall["fired"] = False
                    recall["mounted"] = False
                    recall["abstain"] = True
                    recall["reason"] = "memory_miss"
                    recall["matched_facts"] = []
                    recall["doc_chips"] = []
                    recall["reason_text"] = "没记住的个人属性不交给基座编"
                    recall["expert"] = None
                    recall["mounted_expert"] = None
                    recall["mounted_label"] = "基座"
            if not fact_answer and not open_task and utterance_is_question(content):
                from memory_core.span_guard import asks_memory_chain, fixed_refusal

                if asks_memory_chain(content):
                    fact_answer = fixed_refusal(content)
                    decision.fired = False
                    decision.expert = None
                    decision.label = "基座"
                    decision.reason = "memory_miss"
                    recall["fired"] = False
                    recall["mounted"] = False
                    recall["abstain"] = True
                    recall["reason"] = "memory_miss"
                    recall["matched_facts"] = []
                    recall["reason_text"] = "前半句点了名字，后半句问的角色不在记忆里"
                    recall["mounted_expert"] = None
                    recall["mounted_label"] = "基座"
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

    def list_pending(self) -> list[dict]:
        from memory_core.documents import fact_from_point, queued_lines
        from memory_core.same_memory import normalize_fact_key

        stored = [str(row.get("statement") or "") for row in self._stored_rows()]
        stored.extend(str(row.get("value") or "") for row in self._stored_rows())
        items = []
        seen: set[str] = set()

        def take(fact: dict) -> None:
            from memory_core.extract import is_imperative_request, is_question_fragment

            statement = str(fact.get("statement") or "")
            if not statement or is_question_fragment(statement) or is_imperative_request(statement):
                return
            if any(is_same_memory(statement, item) for item in stored if item):
                return
            key = normalize_fact_key(statement)
            if not key or key in seen:
                return
            seen.add(key)
            fact = dict(fact)
            fact["selected"] = True
            fact["id"] = fact.get("id") or f"p{len(items) + 1}"
            items.append(_public_fact(fact))

        for conv in self.list_conversations():
            for fact in pattern_extract(self.convos.user_text(conv["id"])):
                fact["source_conversations"] = [{"id": conv["id"], "title": conv["title"]}]
                take(fact)
        for row in queued_lines(self.home):
            fact = fact_from_point(row["text"], row["title"], row.get("chapter") or "")
            fact["source_conversations"] = [{"id": row["doc_id"], "title": row["title"]}]
            fact["doc_id"] = row["doc_id"]
            take(fact)
        return items

    def train_pending(self) -> dict[str, Any]:
        facts = self.list_pending()
        if not facts:
            raise ServiceError("没有待巩固的事实")
        return self.start_consolidation([], facts, preview_id=None)

    def list_documents(self) -> list[dict]:
        from memory_core.documents import list_documents

        stored = [str(row.get("statement") or "") for row in self._stored_rows()]
        rows = []
        for doc in list_documents(self.home, stored):
            rows.append({
                "id": doc["id"],
                "title": doc["title"],
                "format": doc.get("format") or "",
                "pages": doc["pages"],
                "chunks": doc["chunks"],
                "points": doc["points"],
                "queued": len(doc.get("queued") or []),
                "consolidated": doc["consolidated"],
            })
        return rows

    def document_status(self) -> dict:
        from memory_core.documents import docs_root

        path = docs_root(self.home) / "job.json"
        if not path.is_file():
            return {"phase": "idle", "percent": 0, "title": "", "message": ""}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"phase": "idle", "percent": 0, "title": "", "message": ""}

    def start_document_import(self, source: str) -> dict:
        path = Path(source)
        if not path.is_file():
            raise ServiceError("找不到这份文档")
        suffix = path.suffix.lower()
        if suffix not in {".pdf", ".txt", ".epub", ".docx", ".md"}:
            raise ServiceError("只能导入 PDF、TXT、EPUB 或 DOCX")
        if self._preview_running():
            raise ServiceError("正在读入文档，请等这一轮结束")

        def _ask(prompt: str) -> str:
            if os.environ.get("LORA_MEMORY_E2E_FAST") == "1":
                return ""
            try:
                self.ensure_ready()
                with self._lock:
                    self.chat.ensure()
                    from memory_core.routing import RouteDecision

                    decision = RouteDecision(False, None, 0.0, "基座", "no_experts", False, False)
                    return self.chat.reply(
                        [{"role": "user", "content": prompt}],
                        decision,
                        max_new_tokens=64,
                        max_seconds=20,
                    )
            except Exception:
                return ""

        def _embed(texts: list[str]):
            self.ensure_ready()
            bind_bge(self.models_dir)
            from router import embed

            return [[float(value) for value in row] for row in embed(texts)]

        holder: dict[str, Any] = {"error": None}

        def _run() -> None:
            try:
                from memory_core.documents import import_document

                embed = None if os.environ.get("LORA_MEMORY_E2E_FAST") == "1" else _embed
                holder["result"] = import_document(self.home, path, embed=embed, ask=_ask)
            except Exception as exc:
                holder["error"] = str(exc)
                from memory_core.documents import docs_root

                atomic_write_json(docs_root(self.home) / "job.json", {
                    "phase": "error",
                    "percent": 0,
                    "title": path.stem,
                    "message": str(exc),
                })

        self._preview_thread = threading.Thread(target=_run, name="doc-import", daemon=True)
        self._preview_thread.start()
        return self.document_status()

    def cancel_document_import(self) -> dict:
        from memory_core.documents import docs_root

        flag = docs_root(self.home) / "CANCEL"
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text("1", encoding="utf-8")
        return self.document_status()

    def queue_document_points(self, doc_id: str, point_ids: list[str]) -> dict:
        from memory_core.documents import queue_points

        try:
            queued = queue_points(self.home, doc_id, point_ids)
        except FileNotFoundError as exc:
            raise ServiceError("找不到这份文档") from exc
        return {"queued": len(queued), "pending": self.list_pending()}

    def remove_document(self, doc_id: str) -> dict:
        from memory_core.documents import delete_document

        try:
            delete_document(self.home, doc_id)
        except FileNotFoundError as exc:
            raise ServiceError("找不到这份文档") from exc
        return {"ok": True, "pending": self.list_pending()}

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
                if entity.casefold() == value.casefold() and not str(fact.get("statement") or "").startswith("我的"):
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

    def _experts_for_route(self, route: str) -> list:
        """同一主体已经有的可写专家。关于使用者的事实认 self 标记或全部是说话人的事实。"""
        found = []
        for record in self.expert_records():
            if not record.writable or not record.explicit or not record.fact_memory:
                continue
            stored = list(record.fact_memory.get("facts") or [])
            key = sole_route(stored)
            if key == route:
                found.append(record)
            elif route == SELF_ROUTE and record.fact_memory.get("self") and key is None:
                found.append(record)
        return found

    def _consolidation_groups(self, expanded: list[dict], sources: list[dict]) -> list[dict]:
        """按主体拆开。说话人并进已有的「关于你」，别的实体各用自己的专家。"""
        groups = []
        for route, items in group_facts(expanded):
            matches = self._experts_for_route(route)
            matches.sort(key=lambda record: (
                -sum(1 for fact in (record.fact_memory or {}).get("facts") or [] if isinstance(fact, dict) and not fact.get("superseded")),
                record.name,
            ))
            primary = matches[0] if matches else None
            extras = matches[1:]
            prior: list[dict] = []
            prior_sources: list[dict] = []
            for record in matches:
                prior.extend(list(record.fact_memory.get("facts") or []))
                prior_sources.extend(list(record.sources or []))
            merged = merge_route_facts(prior, items)
            training = []
            for fact in merged:
                if fact.get("superseded"):
                    continue
                if fact.get("qa") and fact.get("statement") and (fact.get("value") or fact.get("answer")):
                    item = dict(fact)
                else:
                    item = expand_training_fact(fact)
                    item["id"] = fact.get("id") or ""
                    item["source_conversations"] = fact.get("source_conversations") or []
                    item["raw"] = fact.get("raw") or ""
                item["selected"] = True
                item["gate"] = item.get("gate") or "write"
                training.append(item)
            seen_sources: set[str] = set()
            group_sources = []
            fact_sources = []
            for fact in training:
                fact_sources.extend(list(fact.get("source_conversations") or []))
            for src in list(prior_sources) + list(sources) + fact_sources:
                if not isinstance(src, dict):
                    continue
                sid = str(src.get("id") or "")
                if not sid or sid in seen_sources:
                    continue
                seen_sources.add(sid)
                group_sources.append({"id": sid, "title": src.get("title") or sid})
            batch = None
            if primary is not None:
                batch = int(primary.batch) if primary.batch is not None else next_batch_id(self.experts_dir)
            groups.append({
                "route": route,
                "self": route == SELF_ROUTE,
                "display_name": SELF_DISPLAY if route == SELF_ROUTE else route,
                "facts": training,
                "memory_facts": merged,
                "replace_name": primary.name if primary is not None else "",
                "replace_batch": batch,
                "retire": [record.name for record in extras],
                "sources": group_sources,
            })
        return groups

    def start_consolidation(self, conversation_ids: list[str], facts: list[dict], preview_id: str | None = None) -> dict[str, Any]:
        self._reconcile_current_job()
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
            item["source"] = fact.get("source") or ""
            item["source_conversations"] = fact.get("source_conversations") or []
            item["gate_reason"] = fact.get("gate_reason") or ""
            expanded.append(item)
        sources = []
        for conv_id in conversation_ids:
            conv = self.convos.get(conv_id)
            if conv is not None:
                sources.append({"id": conv_id, "title": conv["title"]})
        for item in expanded:
            if not item.get("source_conversations"):
                item["source_conversations"] = sources
        groups = self._consolidation_groups(expanded, sources)
        display = expert_display_name(expanded)
        job_id = time.strftime("job_%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:4]
        self._proc_job = job_id
        job_dir = self.jobs_dir / job_id
        job_dir.mkdir(parents=True)
        request = {
            "facts": expanded,
            "groups": groups,
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
        if os.environ.get("LORA_MEMORY_E2E_FAST") == "1":
            request["epochs"] = 1
            request["min_epochs"] = 1
            request["patience"] = 1
            request["target_loss"] = 99
            request["fast"] = True
        covered_ids = set()
        for item in expanded:
            for source in item.get("source_conversations") or []:
                if source.get("id"):
                    covered_ids.add(source["id"])
        request["empty_sources"] = [item for item in sources if item.get("id") not in covered_ids]
        atomic_write_json(job_dir / "request.json", request)
        trace_events = self._trace_events(preview_id, sources, expanded)
        stages = _stages_from_trace(trace_events)
        for stage in stages:
            if stage.get("id") == "gate":
                stage["detail"] = f"保留 {len(expanded)} 条，跳过 0 条"
                stage["state"] = "done"
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
        self._proc_job = job_id
        self._proc = subprocess.Popen(
            [sys.executable, "-m", "memory_core.train_worker", "--home", str(self.home), "--job-id", job_id],
            cwd=root,
            env=env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
        proc = self._proc
        status = self.job_status(job_id)
        status["worker_pid"] = proc.pid
        atomic_write_json(job_dir / "status.json", status)

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

    def _worker_alive(self, job_id: str, status: dict) -> bool:
        from memory_core.job_recover import pid_alive

        if self._proc is not None and self._proc.poll() is None and self._proc_job in {None, "", job_id}:
            return True
        if self._proc_job == job_id and self._proc is None:
            return True
        return pid_alive(status.get("worker_pid"))

    def _reconcile_job(self, job_id: str) -> dict:
        from memory_core.job_recover import finalize_dead_job

        job_dir = self.jobs_dir / job_id
        status = self.job_status(job_id)
        if status.get("status") != "running" or self._worker_alive(job_id, status):
            return status
        status = finalize_dead_job(status, cancel_requested=(job_dir / "CANCEL").is_file() or bool(status.get("cancel_requested")))
        atomic_write_json(job_dir / "status.json", status)
        return status

    def _reconcile_current_job(self) -> None:
        pointer = self.jobs_dir / "current.json"
        if not pointer.is_file():
            return
        try:
            job_id = read_json(pointer)["id"]
        except (json.JSONDecodeError, KeyError, OSError):
            return
        if not (self.jobs_dir / job_id / "status.json").is_file():
            return
        self._reconcile_job(job_id)

    def job_running(self) -> bool:
        """状态已经结束时不再挡住对话。进程没了就先把任务标成中断。"""
        self._reconcile_current_job()
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
        status = self._reconcile_job(job_id)
        if status.get("status") != "running":
            return status
        status["cancel_requested"] = True
        status["message"] = "正在停止，当前这一小步结束后可以继续"
        atomic_write_json(job_dir / "status.json", status)
        return status

    def resume_job(self, job_id: str) -> dict:
        self._reconcile_current_job()
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
        self._proc_job = job_id
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
            "self_expert": bool((record.fact_memory or {}).get("self")) or facts_are_self(facts),
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
            stored_facts = [
                fact for fact in ((record.fact_memory or {}).get("facts") or [])
                if isinstance(fact, dict) and not fact.get("superseded")
            ]
            if not stored_facts and not (record.fact_memory or {}).get("self"):
                continue
            experts.append({
                "id": f"expert:{record.name}",
                "name": record.name,
                "display_name": record.display_name,
                "writable": record.writable,
                "explicit": record.explicit,
                "self": bool((record.fact_memory or {}).get("self")) or facts_are_self(stored_facts),
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
                    "attr": _nebula_attr(str(fact.get("attr") or ""), str(fact.get("statement") or "")),
                    "value": _nebula_value(str(fact.get("value") or fact.get("answer") or ""), str(fact.get("statement") or "")),
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
                if entity and not speaker_pronoun(entity) and not fact.get("superseded") and entity not in names:
                    names.append(entity)
            if not names:
                names = [entity for entity in record.entities if 2 <= len(entity) <= 12]
            canonical[record.name] = names
            bank = ensure_fact_bank(record) if record.explicit else None
            vec = None
            if bank is not None and bank.question_vecs.numel():
                raw = bank.question_vecs
                if not (getattr(raw, "is_meta", False) or getattr(raw.device, "type", "") == "meta"):
                    vec = raw.detach().float().cpu().mean(dim=0)
            if vec is None and record.key is not None and not (
                getattr(record.key, "is_meta", False) or getattr(record.key.device, "type", "") == "meta"
            ):
                vec = record.key.detach().float().cpu().mean(dim=0)
            if vec is None:
                continue
            norm = float(vec.norm()) or 1.0
            centroids[record.name] = vec / norm
        names_in_order = [name for name in centroids]
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
        source_titles: dict[str, str] = {}
        for record in records:
            for fact in (record.fact_memory or {}).get("facts") or []:
                if not isinstance(fact, dict):
                    continue
                for source in fact.get("source_conversations") or []:
                    sid = str(source.get("id") or "")
                    title = str(source.get("title") or "").strip()
                    if sid and title and title != sid:
                        source_titles[sid] = title
        try:
            from memory_core.documents import list_documents

            for doc in list_documents(self.home):
                if doc.get("id") and doc.get("title"):
                    source_titles.setdefault(str(doc["id"]), str(doc["title"]))
        except Exception:
            pass
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
                title = (conv["title"] if conv else "") or source_titles.get(conv_id) or ""
                if not title or title == conv_id:
                    title = source_titles.get(conv_id) or "文档"
                conversations.append({
                    "id": f"conv:{conv_id}",
                    "conversation_id": conv_id,
                    "title": title,
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

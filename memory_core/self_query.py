"""第一人称问的是使用者。只有「你是谁」才介绍助手。"""
from __future__ import annotations

import re
from typing import Any

from memory_core.extract import speaker_pronoun
from memory_core.prompts import has_cjk


def _norm(text: str) -> str:
    return str(text or "").strip().strip("？?。.!！! ")


def self_ask(query: str) -> str | None:
    """identity / name / place / overview / assistant。不是在问自己时返回 None。"""
    q = _norm(query)
    if not q:
        return None
    lower = q.casefold()
    about_user = "我" in q or bool(re.search(r"\b(i|me|my)\b", lower))
    assistant = (not about_user) and (
        q.startswith("你是谁")
        or q.startswith("你叫什么")
        or bool(re.search(r"\bwho are you\b", lower))
        or bool(re.search(r"what(?:'s| is) your name\b", lower))
    )
    if assistant:
        return "assistant"
    if q == "我是谁" or q.startswith("我是谁") or re.search(r"\bwho am i\b", lower):
        return "identity"
    if q.startswith("我叫什么") or q.startswith("我的名字") or re.search(r"what(?:'s| is) my name\b", lower):
        return "name"
    if q.startswith("我住") or re.search(r"\bwhere (?:do i live|am i from)\b", lower):
        return "place"
    if "关于我" in q or "你知道我" in q or "你了解我" in q or re.search(r"what do you know about me\b", lower):
        return "overview"
    return None


def _is_user_name(fact: dict) -> bool:
    entity = str(fact.get("entity") or "").strip()
    if not speaker_pronoun(entity):
        return False
    attr = str(fact.get("attr") or "")
    if "猫" in attr or "狗" in attr:
        return False
    if attr in {"名字", "姓名"}:
        return True
    statement = str(fact.get("statement") or "").strip()
    return statement.startswith("我叫") or statement.startswith("我是") or statement.startswith("我的名字")


def _active(experts: list[Any]) -> list[dict]:
    rows = []
    for expert in experts:
        memory = getattr(expert, "fact_memory", None) or {}
        if not isinstance(memory, dict):
            continue
        for fact in memory.get("facts") or []:
            if isinstance(fact, dict) and not fact.get("superseded"):
                item = dict(fact)
                item["_expert"] = expert
                rows.append(item)
    return rows


def self_facts(experts: list[Any]) -> list[dict]:
    return [fact for fact in _active(experts) if speaker_pronoun(str(fact.get("entity") or ""))]


def _finish(text: str) -> str:
    trimmed = text.strip()
    if not trimmed:
        return trimmed
    if trimmed[-1] in "。！？.!?":
        return trimmed
    return trimmed + ("。" if has_cjk(trimmed) else ".")


def _voice(statement: str, entity: str) -> str:
    text = str(statement or "").strip()
    if not speaker_pronoun(entity) and not text.startswith("我"):
        return _finish(text)
    if not has_cjk(text):
        spoken = text
        spoken = re.sub(r"\bI'm\b", "you're", spoken, flags=re.IGNORECASE)
        spoken = re.sub(r"\bI am\b", "you are", spoken, flags=re.IGNORECASE)
        spoken = re.sub(r"\bI\b", "you", spoken)
        spoken = re.sub(r"\b[Mm]y\b", lambda match: "Your" if match.group(0)[0].isupper() else "your", spoken)
        return _finish(spoken)
    kept = text.replace("我们", "\uE000")
    yours = kept.replace("我的", "你的").replace("\uE000", "你们")
    yours = re.sub(r"(?<![\u4e00-\u9fff])我(?!们)", "你", yours)
    return _finish(yours)


def unknown_self(kind: str, english: bool) -> str:
    if english and kind == "place":
        return "I don't know where you live yet. You can tell me."
    if english:
        return "I don't know who you are yet. You can tell me."
    if kind == "place":
        return "还不知道你住在哪里。你可以告诉我。"
    return "还不知道你是谁。你可以告诉我。"


def self_reply(query: str, experts: list[Any], english: bool = False) -> tuple[str, Any, list[dict]] | None:
    """命中时返回答案、专家和用到的事实。助手自我介绍返回 None，交给基座。"""
    kind = self_ask(query)
    if kind is None or kind == "assistant":
        return None
    mine = self_facts(experts)
    if kind == "place":
        picked = [fact for fact in mine if "住" in str(fact.get("statement") or "") or "住" in str(fact.get("attr") or "")]
    elif kind == "overview":
        picked = mine
    else:
        picked = [fact for fact in mine if _is_user_name(fact)]
    if kind == "identity" and picked:
        fact = picked[0]
        value = str(fact.get("value") or fact.get("answer") or "").strip() or str(fact.get("statement") or "")
        answer = f"You are {value}." if english else f"你是{value}。"
        return _finish(answer), fact.get("_expert"), [fact]
    if not picked:
        return unknown_self(kind, english), None, []
    lines = []
    for fact in picked:
        spoken = _voice(str(fact.get("statement") or fact.get("value") or ""), str(fact.get("entity") or "我"))
        if spoken and spoken not in lines:
            lines.append(spoken)
    return "".join(lines), picked[0].get("_expert"), picked

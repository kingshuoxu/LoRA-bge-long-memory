"""把 0.2.7 的「用户」并进「关于你」。

旧桌面把说话人存成实体「用户」，显示名常常是「用户/徐金朔」。
新的回忆只认「我」。升级时改写事实，再说一遍已知的名字时也把这条链补上。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from memory_core.extract import SELF_DISPLAY, is_self_entity, legacy_self_entity

_NAME_QUESTIONS = (
    "我是谁？",
    "我叫什么？",
    "我叫什么名字？",
    "我的名字是什么？",
    "我的名字叫什么？",
)


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rewrite_self_statement(statement: str, value: str) -> str:
    text = str(statement or "").strip()
    text = re.sub(r"^(用户|user|关于你)(的名字是|的姓名是|叫|是)", r"我\2", text, flags=re.IGNORECASE)
    if text.startswith("用户"):
        text = "我" + text[len("用户"):]
    if text.startswith("我是"):
        text = "我叫" + text[len("我是"):]
    if not text.startswith("我") and value:
        text = f"我叫{value}"
    if text and text[-1] not in "。.!！？?":
        text += "。"
    return text


def _name_value(fact: dict) -> str:
    value = str(fact.get("value") or fact.get("answer") or "").strip()
    if value and len(value) <= 16 and "。" not in value:
        return value
    statement = str(fact.get("statement") or "")
    match = re.search(r"(?:叫|是)([\u4e00-\u9fffA-Za-z·]{1,16})", statement)
    return match.group(1) if match else value


def _is_legacy_fact(fact: dict) -> bool:
    entity = str(fact.get("entity") or "").strip()
    statement = str(fact.get("statement") or "").strip()
    if legacy_self_entity(entity):
        return True
    return bool(re.match(r"^(用户|user|关于你)(的名字|的姓名|叫|是)", statement, flags=re.IGNORECASE))


def _repair_fact(fact: dict) -> dict:
    item = dict(fact)
    value = _name_value(item)
    item["entity"] = "我"
    item["attr"] = item.get("attr") or "名字"
    if item["attr"] in {"事实", "用户", "名字", "姓名"} or "名" in str(item["attr"]):
        item["attr"] = "名字"
    item["value"] = value
    item["answer"] = value
    item["statement"] = rewrite_self_statement(str(item.get("statement") or ""), value)
    questions = [str(row.get("q") or "") for row in item.get("qa") or [] if isinstance(row, dict)]
    for question in _NAME_QUESTIONS:
        if question not in questions:
            questions.append(question)
    item["qa"] = [{"q": question, "a": value} for question in questions if question]
    item["question"] = item["qa"][0]["q"] if item["qa"] else "我叫什么名字？"
    return item


def _display_for(memory: dict) -> str:
    facts = [fact for fact in memory.get("facts") or [] if isinstance(fact, dict) and not fact.get("superseded")]
    if facts and all(is_self_entity(str(fact.get("entity") or "")) for fact in facts):
        return SELF_DISPLAY
    display = str(memory.get("display_name") or "")
    display = display.replace("用户/", "").replace("用户", SELF_DISPLAY)
    return display or SELF_DISPLAY


def rewrite_memory(memory: dict) -> bool:
    facts = memory.get("facts")
    if not isinstance(facts, list):
        return False
    changed = False
    rewritten = []
    for fact in facts:
        if not isinstance(fact, dict):
            rewritten.append(fact)
            continue
        if fact.get("superseded") or not _is_legacy_fact(fact):
            rewritten.append(fact)
            continue
        rewritten.append(_repair_fact(fact))
        changed = True
    if not changed:
        return False
    memory["facts"] = rewritten
    entities = []
    for name in memory.get("entities") or []:
        text = "我" if legacy_self_entity(str(name)) else str(name)
        if text and text not in entities:
            entities.append(text)
    if "我" not in entities:
        entities.insert(0, "我")
    memory["entities"] = entities
    memory["self"] = True
    memory["display_name"] = _display_for(memory)
    return True


def _update_router(experts_dir: Path, name: str, display: str) -> None:
    path = experts_dir / "router.jsonl"
    if not path.is_file():
        return
    rows = []
    changed = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            rows.append(line)
            continue
        if row.get("expert") == name:
            row["display_name"] = display
            changed = True
        rows.append(json.dumps(row, ensure_ascii=False))
    if changed:
        path.write_text("".join(item + "\n" for item in rows), encoding="utf-8")


def migrate_user_identity(home: Path) -> int:
    """改写专家目录里的旧「用户」事实。没有旧事实时什么都不写。"""
    experts = Path(home) / "experts"
    if not experts.is_dir():
        return 0
    changed = 0
    for path in sorted(experts.glob("*/fact_memory.json")):
        memory = _read(path)
        if not isinstance(memory, dict):
            continue
        if not rewrite_memory(memory):
            continue
        _write(path, memory)
        _update_router(experts, path.parent.name, str(memory.get("display_name") or SELF_DISPLAY))
        changed += 1
    return changed


def repair_identity_link(expert_dir: Path, value: str) -> bool:
    """再说一遍已经记下的名字时，把缺的「我」补上，不另存一条。"""
    path = Path(expert_dir) / "fact_memory.json"
    memory = _read(path)
    if not isinstance(memory, dict):
        return False
    wanted = str(value or "").strip()
    facts = memory.get("facts")
    if not isinstance(facts, list):
        return False
    touched = False
    for index, fact in enumerate(facts):
        if not isinstance(fact, dict) or fact.get("superseded"):
            continue
        current = _name_value(fact)
        if wanted and current and wanted != current:
            continue
        if not _is_legacy_fact(fact) and str(fact.get("entity") or "") == "我":
            continue
        if not _is_legacy_fact(fact) and not is_self_entity(str(fact.get("entity") or "")):
            continue
        facts[index] = _repair_fact(fact)
        touched = True
    if not touched:
        return False
    memory["facts"] = facts
    memory["self"] = True
    memory["display_name"] = SELF_DISPLAY
    entities = [str(name) for name in memory.get("entities") or []]
    entities = ["我" if legacy_self_entity(name) else name for name in entities]
    if "我" not in entities:
        entities.insert(0, "我")
    memory["entities"] = entities
    _write(path, memory)
    _update_router(path.parent.parent, path.parent.name, SELF_DISPLAY)
    return True

"""只清理 0.2.14 误存的要求句。

陈述句即使包含「翻译」「推荐」也留着。清理只跑一次：先备份，再隔离，不直接抹掉。
"""
from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from memory_core.extract import is_imperative_request, is_question_fragment
from memory_core.store import atomic_write_json

log = logging.getLogger("memory_core.migrate_0214")

# desktop-v0.2.14 发布到 desktop-v0.2.15 发布之间。没有版本戳时只认这段时间写下来的。
WINDOW_START = "2026-11-05T04:53:48+00:00"
WINDOW_END = "2026-11-05T08:59:07+00:00"
MARKER = "migrations/cleanup-0214.json"
QUARANTINE = "cleaned/0214-junk.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _version_of(fact: dict, memory: dict, home_version: str) -> str:
    return str(fact.get("app_version") or memory.get("app_version") or home_version or "").strip()


def _created_in_window(fact: dict, memory: dict, path: Path) -> bool:
    created = str(fact.get("created_at") or memory.get("created_at") or "")
    if not created:
        try:
            created = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
        except OSError:
            return False
    return WINDOW_START <= created <= WINDOW_END


def from_buggy_release(fact: dict, memory: dict, home_version: str, path: Path) -> bool:
    """0.2.14 写的，或完全没有版本戳且落在 0.2.14 的发布时间里。"""
    version = _version_of(fact, memory, home_version)
    if version == "0.2.14":
        return True
    if version:
        return False
    return _created_in_window(fact, memory, path)


def is_0214_junk(text: str) -> bool:
    """整句是要求或问句。陈述句一律不是。"""
    return is_imperative_request(text) or is_question_fragment(text)


def _home_version(home: Path) -> str:
    data = _read(home / "app-version.json")
    if isinstance(data, dict):
        return str(data.get("version") or "")
    settings = _read(home / "settings.json")
    if isinstance(settings, dict):
        return str(settings.get("desktop_version") or "")
    return ""


def _backup(home: Path, paths: list[Path], stamp: str) -> Path:
    backup = home / f"memory.bak-{stamp}"
    for path in paths:
        target = backup / path.relative_to(home)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    return backup


def _quarantine(home: Path, items: list[dict]) -> None:
    path = home / QUARANTINE
    current = _read(path)
    rows = current if isinstance(current, list) else []
    rows.extend(items)
    atomic_write_json(path, {"items": rows})


def migrate_0214_junk(home: Path) -> int:
    """隔离 0.2.14 的要求句。已经跑过就什么都不写。"""
    home = Path(home)
    marker = home / MARKER
    if marker.is_file():
        return 0
    experts = home / "experts"
    docs = home / "documents"
    candidates: list[Path] = []
    if experts.is_dir():
        candidates.extend(sorted(experts.glob("*/fact_memory.json")))
    if docs.is_dir():
        candidates.extend(sorted(docs.glob("*/queued.json")))
    home_version = _home_version(home)
    plan: list[tuple[Path, object]] = []
    removed: list[dict] = []
    for path in candidates:
        data = _read(path)
        if path.name == "fact_memory.json":
            if not isinstance(data, dict) or not isinstance(data.get("facts"), list):
                continue
            kept = []
            changed = False
            for fact in data["facts"]:
                if not isinstance(fact, dict):
                    kept.append(fact)
                    continue
                statement = str(fact.get("statement") or fact.get("value") or "")
                if from_buggy_release(fact, data, home_version, path) and is_0214_junk(statement):
                    changed = True
                    removed.append({"file": str(path.relative_to(home)), "fact": fact})
                    log.info("quarantine fact %s from %s", statement, path.name)
                    continue
                kept.append(fact)
            if changed:
                data["facts"] = kept
                names = []
                for fact in kept:
                    name = str(fact.get("entity") or "").strip()
                    if name and name not in names:
                        names.append(name)
                data["entities"] = names
                plan.append((path, data))
        elif isinstance(data, list):
            kept = []
            changed = False
            memory = {"app_version": home_version}
            for item in data:
                text = item if isinstance(item, str) else str((item or {}).get("text") or "")
                fact = item if isinstance(item, dict) else {"statement": text}
                if from_buggy_release(fact, memory, home_version, path) and is_0214_junk(text):
                    changed = True
                    removed.append({"file": str(path.relative_to(home)), "text": text})
                    log.info("quarantine pending %s", text)
                    continue
                kept.append(item)
            if changed:
                plan.append((path, kept))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_name = ""
    if plan:
        _backup(home, [item[0] for item in plan], stamp)
        backup_name = f"memory.bak-{stamp}"
        if removed:
            _quarantine(home, removed)
        for path, payload in plan:
            _atomic_write_any(path, payload)
    marker.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(marker, {"done": True, "at": _now(), "removed": len(removed), "backup": backup_name})
    return len(removed)


def _atomic_write_any(path: Path, payload) -> None:
    if isinstance(payload, dict):
        atomic_write_json(path, payload)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def restore_0214_junk(home: Path) -> int:
    """把隔离出去的条目放回原来的文件。备份不动。"""
    home = Path(home)
    path = home / QUARANTINE
    data = _read(path)
    items = data.get("items") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return 0
    restored = 0
    for item in items:
        if not isinstance(item, dict) or "fact" not in item:
            continue
        target = home / str(item.get("file") or "")
        if target.name != "fact_memory.json":
            continue
        memory = _read(target)
        if not isinstance(memory, dict):
            memory = {"facts": [], "entities": []}
        facts = memory.setdefault("facts", [])
        facts.append(item["fact"])
        atomic_write_json(target, memory)
        restored += 1
    return restored

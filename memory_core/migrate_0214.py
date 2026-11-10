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
RESTORE_MARKER = "migrations/restore-0214-kept.json"
RESTORE_VERSION = 3
CLASSIFIER_VERSION = 4
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


def _marker_version(marker: Path) -> int:
    if not marker.is_file():
        return 0
    data = _read(marker)
    if not isinstance(data, dict):
        return 0
    try:
        return int(data.get("version") or 0)
    except (TypeError, ValueError):
        return 0


def _version_tuple(version: str) -> tuple[int, int, int] | None:
    parts = (version or "").split(".")
    if len(parts) != 3:
        return None
    try:
        return int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return None


def _should_quarantine(fact: dict, memory: dict, home_version: str, path: Path) -> bool:
    """0.2.14 的要求句，以及 0.2.30 之后仍被放进记忆的问句和要求。"""
    statement = str(fact.get("statement") or fact.get("value") or fact.get("text") or "")
    if not statement or not is_0214_junk(statement):
        return False
    if from_buggy_release(fact, memory, home_version, path):
        return True
    parsed = _version_tuple(_version_of(fact, memory, home_version))
    return parsed is not None and parsed >= (0, 2, 30)


def migrate_0214_junk(home: Path) -> int:
    """隔离要求句和问句。分类器变了就再跑一遍，旧标记不再挡住。"""
    home = Path(home)
    marker = home / MARKER
    if _marker_version(marker) >= CLASSIFIER_VERSION:
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
                if _should_quarantine(fact, data, home_version, path):
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
                if _should_quarantine(fact, memory, home_version, path):
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
    atomic_write_json(marker, {
        "done": True,
        "version": CLASSIFIER_VERSION,
        "at": _now(),
        "removed": len(removed),
        "backup": backup_name,
    })
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


def _statement_of(fact: dict) -> str:
    return str(fact.get("statement") or fact.get("value") or "").strip()


def _inside(home: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(home.resolve())
    except (OSError, ValueError):
        return False
    return True


def _append_missing_fact(home: Path, relative: str, fact: dict, *, allow_junk: bool = False) -> bool:
    """把事实放回原来的专家文件。已有的不重复放。自动恢复时跳过仍然是垃圾的句子。"""
    target = home / relative
    if not _inside(home, target) or target.name != "fact_memory.json":
        return False
    statement = _statement_of(fact)
    if not statement or (not allow_junk and is_0214_junk(statement)):
        return False
    memory = _read(target)
    if not isinstance(memory, dict):
        memory = {"facts": [], "entities": []}
    facts = memory.setdefault("facts", [])
    if any(isinstance(item, dict) and _statement_of(item) == statement for item in facts):
        return False
    facts.append(fact)
    names = []
    for item in facts:
        if not isinstance(item, dict):
            continue
        name = str(item.get("entity") or "").strip()
        if name and name not in names:
            names.append(name)
    memory["entities"] = names
    atomic_write_json(target, memory)
    return True


def _restore_version(marker: Path) -> int:
    if not marker.is_file():
        return 0
    data = _read(marker)
    if not isinstance(data, dict):
        return 1
    try:
        return int(data.get("version") or 1)
    except (TypeError, ValueError):
        return 1


def restore_legitimate_from_cleanup(home: Path) -> int:
    """只从隔离区或 memory.bak-* 把陈述句放回去。0.2.15 当时直接删、没有备份，就无从恢复。

    旧版本的恢复标记不会挡住后来收紧的分类器。已经放回去的句子不会再复制一份。
    """
    home = Path(home)
    marker = home / RESTORE_MARKER
    if _restore_version(marker) >= RESTORE_VERSION:
        return 0
    restored = 0
    quarantine_path = home / QUARANTINE
    data = _read(quarantine_path)
    items = data.get("items") if isinstance(data, dict) else []
    if not isinstance(items, list):
        items = []
    remaining = []
    for item in items:
        if not isinstance(item, dict):
            remaining.append(item)
            continue
        fact = item.get("fact") if isinstance(item.get("fact"), dict) else None
        text = _statement_of(fact) if fact else str(item.get("text") or "")
        relative = str(item.get("file") or "")
        if text and is_0214_junk(text):
            _drop_junk_copy(home, relative, text)
            remaining.append(item)
            continue
        if fact and text and _append_missing_fact(home, relative, fact):
            restored += 1
            continue
        if not fact and text and _append_pending(home, relative, text):
            restored += 1
            continue
        remaining.append(item)
    if quarantine_path.is_file():
        atomic_write_json(quarantine_path, {"items": remaining})
    for backup in sorted(home.glob("memory.bak-*")):
        if not backup.is_dir():
            continue
        for path in backup.glob("experts/*/fact_memory.json"):
            memory = _read(path)
            if not isinstance(memory, dict):
                continue
            relative = path.relative_to(backup).as_posix()
            for fact in memory.get("facts") or []:
                if isinstance(fact, dict) and _append_missing_fact(home, relative, fact):
                    restored += 1
    marker.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(marker, {"done": True, "version": RESTORE_VERSION, "at": _now(), "restored": restored})
    return restored


def _drop_junk_copy(home: Path, relative: str, text: str) -> None:
    """隔离区里仍是问句或要求的句子，如果上一轮误放回去了，按原文拿掉。别的事实不动。"""
    if relative.endswith("fact_memory.json"):
        target = home / relative
        if _inside(home, target) and target.is_file():
            memory = _read(target)
            if isinstance(memory, dict):
                facts = [
                    fact for fact in memory.get("facts") or []
                    if not (isinstance(fact, dict) and _statement_of(fact) == text)
                ]
                if len(facts) != len(memory.get("facts") or []):
                    memory["facts"] = facts
                    atomic_write_json(target, memory)
        return
    if not relative.endswith("queued.json"):
        return
    target = home / relative
    if not _inside(home, target) or not target.is_file():
        return
    rows = _read(target)
    if not isinstance(rows, list):
        return
    kept = [item for item in rows if item != text]
    if len(kept) != len(rows):
        _atomic_write_any(target, kept)


def _pending_has(rows: list, text: str) -> bool:
    for item in rows:
        if item == text:
            return True
        if isinstance(item, dict) and str(item.get("text") or item.get("statement") or "") == text:
            return True
    return False


def _append_pending(home: Path, relative: str, text: str) -> bool:
    target = home / relative
    if not text or not _inside(home, target) or target.name != "queued.json":
        return False
    rows = _read(target)
    if not isinstance(rows, list):
        rows = []
    if _pending_has(rows, text):
        return False
    rows.append(text)
    _atomic_write_any(target, rows)
    return True


def restore_0214_junk(home: Path) -> int:
    """把隔离出去的事实和待巩固放回原处。再调一次不会复制。备份不动。"""
    home = Path(home)
    path = home / QUARANTINE
    data = _read(path)
    items = data.get("items") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return 0
    restored = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        relative = str(item.get("file") or "")
        if isinstance(item.get("fact"), dict):
            if _append_missing_fact(home, relative, item["fact"], allow_junk=True):
                restored += 1
            continue
        text = str(item.get("text") or "")
        if text and _append_pending(home, relative, text):
            restored += 1
    return restored

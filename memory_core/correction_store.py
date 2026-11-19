"""Confirmed corrections outlive adapter jobs and expert directory replacement."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from memory_core.store import atomic_write_json


def _path(home: Path) -> Path:
    return Path(home) / "corrections.json"


def _rows(home: Path) -> list[dict]:
    try:
        payload = json.loads(_path(home).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    if payload.get("version") != 1 or not isinstance(payload.get("corrections"), list):
        raise ValueError("Unsupported correction ledger")
    return payload["corrections"]


def _write(home: Path, rows: list[dict]) -> None:
    atomic_write_json(_path(home), {"version": 1, "corrections": rows})


def save_correction(home: Path, expert: str, old_fact: dict, new_fact: dict) -> None:
    """Commit a confirmed correction; the service serializes read-modify-write."""
    old_id, new_id = old_fact.get("id"), new_fact.get("id")
    if not expert or not old_id or not new_id or old_id == new_id:
        raise ValueError("A correction requires an expert and distinct fact IDs")
    rows = _rows(home)
    for row in rows:
        if row["expert"] != expert:
            continue
        if old_id == row["old_fact"]["id"] or new_id in (
            row["old_fact"]["id"], row["new_fact"]["id"]
        ):
            raise ValueError("The correction was already replaced")
    _write(home, [*rows, {"expert": expert, "old_fact": old_fact, "new_fact": new_fact}])


def _active(rows: list[dict]) -> list[dict]:
    replaced = {(row["expert"], row["old_fact"]["id"]) for row in rows}
    return [
        row for row in rows
        if (row["expert"], row["new_fact"]["id"]) not in replaced
    ]


def active_corrections(home: Path) -> list[dict]:
    """Read the active leaves even if an interrupted registration hid the adapter."""
    return _active(_rows(home))


def discard_corrections(home: Path, expert: str) -> None:
    """Prevent deleted experts' corrections from reappearing if names are reused."""
    rows = _rows(home)
    remaining = [row for row in rows if row["expert"] != expert]
    if len(remaining) != len(rows):
        _write(home, remaining)


def apply_corrections(home: Path, records: list) -> list:
    """Apply the durable fact chain to writable records without altering other facts."""
    by_expert: dict[str, list[dict]] = defaultdict(list)
    for row in _rows(home):
        by_expert[row["expert"]].append(row)
    for record in records:
        rows = by_expert.get(record.name)
        if not record.writable or not rows or not isinstance(record.fact_memory, dict):
            continue
        facts = list(record.fact_memory.get("facts") or [])
        indices = {
            str(fact.get("id") or f"{record.name}#{index}"): index
            for index, fact in enumerate(facts) if isinstance(fact, dict)
        }
        on_disk = {key: facts[index] for key, index in indices.items()}
        # A successful registration retains both the superseded row and current row.
        # Job status alone cannot establish what the adapter/index actually contains.
        record.correction_pending = getattr(record, "correction_pending", False) or any(
            not on_disk.get(row["old_fact"]["id"], {}).get("superseded")
            or not on_disk.get(row["new_fact"]["id"])
            or on_disk[row["new_fact"]["id"]].get("superseded")
            or on_disk[row["new_fact"]["id"]].get("value") != row["new_fact"].get("value")
            for row in _active(rows)
        )

        def put(item: dict) -> None:
            fact_id = item["id"]
            if fact_id in indices:
                facts[indices[fact_id]] = item
            else:
                indices[fact_id] = len(facts)
                facts.append(item)

        for row in rows:
            old, new = row["old_fact"], row["new_fact"]
            old_index = indices.get(old["id"])
            existing = facts[old_index] if old_index is not None else old
            put({**existing, "id": old["id"], "superseded": True, "superseded_by": new["id"]})
            put(dict(new))
        record.fact_memory = {**record.fact_memory, "facts": facts}
        if record.correction_pending:
            record.fact_bank = None
    # Imported/re-consolidated copies are not independent authority for the exact
    # predicate and rejected value. Suppress those copies in memory, not on disk.
    rejected = {}
    for row in _rows(home):
        old = row["old_fact"]
        key = (str(old.get("entity") or "").casefold(), str(old.get("attr") or "").casefold(), str(old.get("value") or old.get("answer") or ""))
        rejected[key] = row["new_fact"]["id"]
    for record in records:
        memory = record.fact_memory or {}
        facts = []
        changed = False
        for fact in memory.get("facts") or []:
            key = (str(fact.get("entity") or "").casefold(), str(fact.get("attr") or "").casefold(), str(fact.get("value") or fact.get("answer") or ""))
            if not fact.get("superseded") and key in rejected and not fact.get("corrects"):
                fact = {**fact, "superseded": True, "superseded_by": rejected[key]}
                changed = True
            facts.append(fact)
        if changed:
            record.fact_memory = {**memory, "facts": facts}
            record.correction_pending = True
            record.fact_bank = None
    return records

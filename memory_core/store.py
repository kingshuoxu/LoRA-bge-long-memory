"""专家目录：router.jsonl、router_key.pt、key_texts.json、fact_memory.json、fact_gate.json。

旧的五个研究专家没有 fact_memory.json，读取时退回 key_texts 的实体抽取。
新专家把实体、事实和来源对话写进 fact_memory.json，路由和边界守卫读这份表。
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import torch

from memory_core.gate import fact_gate_config
from memory_core.paths import ensure_scripts_path


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def weights_ready(expert_dir: Path) -> bool:
    weight = expert_dir / "adapter_model.safetensors"
    if not weight.is_file():
        return False
    if weight.stat().st_size < 1000:
        return False
    head = weight.read_bytes()[:40]
    if head.startswith(b"version https://git-lfs"):
        return False
    return True


def resolve_key_path(experts_dir: Path, key_path: str) -> Path:
    raw = Path(str(key_path).replace("\\", "/"))
    if raw.is_absolute() and raw.is_file():
        return raw
    candidates = [
        raw,
        experts_dir / raw,
        experts_dir.parent / raw,
        experts_dir / raw.name,
    ]
    if raw.parts:
        candidates.append(experts_dir / raw.parts[-2] / raw.name if len(raw.parts) >= 2 else experts_dir / raw.name)
        if len(raw.parts) >= 2:
            candidates.append(experts_dir / raw.parts[-2] / "router_key.pt")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return experts_dir / raw


def load_gate(experts_dir: Path) -> dict[str, float]:
    defaults = fact_gate_config()
    path = experts_dir / "fact_gate.json"
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        for key in defaults:
            if key in data:
                defaults[key] = float(data[key])
    return defaults


def ensure_gate_file(experts_dir: Path) -> None:
    path = experts_dir / "fact_gate.json"
    if path.is_file():
        return
    experts_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fact_gate_config(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@dataclass
class ExpertRecord:
    name: str
    directory: Path
    experts_dir: Path
    writable: bool
    key_path: Path
    key: torch.Tensor
    entities: list[str]
    explicit: bool
    display_name: str
    n_facts: int
    rank: int
    batch: int | None
    fact_memory: dict[str, Any] | None
    sources: list[dict[str, str]] = field(default_factory=list)
    entry: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        facts = []
        if self.fact_memory:
            for fact in self.fact_memory.get("facts", []):
                qa = fact.get("qa") or []
                facts.append({
                    "statement": fact.get("statement", ""),
                    "entity": fact.get("entity", ""),
                    "attr": fact.get("attr", ""),
                    "value": fact.get("value", ""),
                    "question": qa[0]["q"] if qa else "",
                    "answer": qa[0]["a"] if qa else fact.get("value", ""),
                })
        else:
            texts_path = self.directory / "key_texts.json"
            if texts_path.is_file():
                texts = json.loads(texts_path.read_text(encoding="utf-8"))
                for text in texts:
                    if isinstance(text, str) and text.endswith("。"):
                        facts.append({"statement": text, "entity": "", "attr": "", "value": "", "question": "", "answer": ""})
                        if len(facts) >= 80:
                            break
        return {
            "name": self.name,
            "display_name": self.display_name,
            "writable": self.writable,
            "n_facts": self.n_facts or len(facts),
            "entities": self.entities,
            "rank": self.rank,
            "sources": self.sources,
            "facts": facts,
            "explicit": self.explicit,
        }


def _display_name(entities: list[str], fallback: str) -> str:
    if not entities:
        return fallback
    shown = "、".join(entities[:2])
    if len(entities) > 2:
        shown += "等"
    return shown


def load_record(experts_dir: Path, entry: dict, writable: bool) -> ExpertRecord | None:
    ensure_scripts_path()
    from router import extract_entities_from_key_texts

    name = entry["expert"]
    key_path = resolve_key_path(experts_dir, entry.get("key_path", ""))
    directory = key_path.parent
    if not key_path.is_file():
        return None
    key = torch.load(key_path, weights_only=True).float().cpu()
    if key.dim() == 1:
        key = key.unsqueeze(0)
    memory_path = directory / "fact_memory.json"
    fact_memory = None
    explicit = False
    sources: list[dict[str, str]] = []
    if memory_path.is_file():
        fact_memory = json.loads(memory_path.read_text(encoding="utf-8"))
        explicit = True
        entities = [str(item) for item in fact_memory.get("entities", []) if str(item).strip()]
        sources = list(fact_memory.get("source_conversations") or [])
        display = fact_memory.get("display_name") or _display_name(entities, name)
    else:
        texts_path = directory / "key_texts.json"
        texts = json.loads(texts_path.read_text(encoding="utf-8")) if texts_path.is_file() else []
        entities = extract_entities_from_key_texts(texts)
        display = _display_name(entities, name)
    return ExpertRecord(
        name=name,
        directory=directory,
        experts_dir=experts_dir,
        writable=writable,
        key_path=key_path,
        key=key,
        entities=entities,
        explicit=explicit,
        display_name=display,
        n_facts=int(entry.get("n_facts") or (len(fact_memory.get("facts", [])) if fact_memory else 0)),
        rank=int(entry.get("rank") or 32),
        batch=entry.get("batch"),
        fact_memory=fact_memory,
        sources=sources,
        entry=entry,
    )


def load_experts(experts_dir: Path, writable: bool, tombstones: set[str] | None = None) -> list[ExpertRecord]:
    tombstones = tombstones or set()
    records = []
    for entry in _read_jsonl(Path(experts_dir) / "router.jsonl"):
        if entry.get("expert") in tombstones:
            continue
        try:
            record = load_record(experts_dir, entry, writable)
        except Exception:
            continue
        if record is not None:
            records.append(record)
    return records


def next_batch_id(experts_dir: Path) -> int:
    used = []
    for entry in _read_jsonl(experts_dir / "router.jsonl"):
        try:
            used.append(int(entry.get("batch")))
        except (TypeError, ValueError):
            continue
    start = 1000
    return max([start - 1, *used]) + 1


def guard_entity_aliases(entities: list[str], texts: list[str]) -> list[str]:
    """登记守卫能认的实体写法。

    scripts/router.py 的 extract_query_entity 会把「最喜欢」这类修饰词吞进实体名，
    例如「沈星河最喜欢的茶是什么？」抽出的是「沈星河最喜欢」。守卫要精确相等。
    这里把以已登记实体开头的较长写法补进名册，不改 router.py，展示名仍用原实体。
    """
    canonical = [entity for entity in entities if entity]
    if not canonical or not texts:
        return list(canonical)
    ensure_scripts_path()
    from router import extract_query_entity

    merged = list(canonical)
    for text in texts:
        found = extract_query_entity(str(text))
        if not found or found in merged:
            continue
        if any(found.startswith(entity) and len(found) > len(entity) for entity in canonical):
            merged.append(found)
    return merged


def register_expert(
    experts_dir: Path,
    name: str,
    batch: int,
    rank: int,
    facts: list[dict],
    key: torch.Tensor,
    key_texts: list[str],
    entities: list[str],
    sources: list[dict[str, str]],
    display_name: str,
    adapter_src: Path,
) -> Path:
    """把训练好的 adapter 登记进专家库。adapter_src 是 save_pretrained 的目录。"""
    experts_dir = Path(experts_dir)
    expert_dir = experts_dir / name
    if expert_dir.exists():
        shutil.rmtree(expert_dir)
    expert_dir.mkdir(parents=True)
    for item in Path(adapter_src).iterdir():
        if item.name.startswith("."):
            continue
        target = expert_dir / item.name
        if item.is_file():
            shutil.copy2(item, target)
    torch.save(key.cpu(), expert_dir / "router_key.pt")
    (expert_dir / "key_texts.json").write_text(json.dumps(key_texts, ensure_ascii=False), encoding="utf-8")
    alias_texts = list(key_texts)
    for fact in facts:
        alias_texts.append(str(fact.get("statement") or ""))
        for qa in fact.get("qa") or []:
            alias_texts.append(str(qa.get("q") or ""))
    entities = guard_entity_aliases(entities, alias_texts)
    memory = {
        "expert": name,
        "display_name": display_name,
        "entities": entities,
        "source_conversations": sources,
        "facts": facts,
    }
    (expert_dir / "fact_memory.json").write_text(json.dumps(memory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ensure_gate_file(experts_dir)
    entry = {
        "expert": name,
        "batch": batch,
        "n_facts": len(facts),
        "rank": rank,
        "key_path": str(Path(name) / "router_key.pt"),
        "display_name": display_name,
        "source_conversations": [item.get("id") for item in sources],
    }
    rows = [row for row in _read_jsonl(experts_dir / "router.jsonl") if row.get("expert") != name and row.get("batch") != batch]
    rows.append(entry)
    rows.sort(key=lambda row: int(row.get("batch") or 0))
    _write_jsonl(experts_dir / "router.jsonl", rows)
    return expert_dir


def delete_writable_expert(experts_dir: Path, name: str) -> None:
    rows = _read_jsonl(experts_dir / "router.jsonl")
    kept = []
    found = False
    for row in rows:
        if row.get("expert") == name:
            found = True
            key_path = resolve_key_path(experts_dir, row.get("key_path", ""))
            directory = key_path.parent
            if directory.is_dir() and directory.parent.resolve() == experts_dir.resolve():
                shutil.rmtree(directory)
            continue
        kept.append(row)
    if not found:
        directory = experts_dir / name
        if directory.is_dir():
            shutil.rmtree(directory)
            found = True
    if not found:
        raise KeyError(name)
    _write_jsonl(experts_dir / "router.jsonl", kept)


def tombstone_path(home: Path) -> Path:
    return home / "deleted_experts.json"


def read_tombstones(home: Path) -> set[str]:
    path = tombstone_path(home)
    if not path.is_file():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    return set(data)


def add_tombstone(home: Path, name: str) -> None:
    names = read_tombstones(home)
    names.add(name)
    tombstone_path(home).write_text(json.dumps(sorted(names), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def file_stamp(paths: list[Path]) -> float:
    stamp = 0.0
    for path in paths:
        if path.is_file():
            stamp = max(stamp, path.stat().st_mtime)
    return stamp


def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)

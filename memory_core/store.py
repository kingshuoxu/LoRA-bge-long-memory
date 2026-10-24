"""专家目录：router.jsonl、router_key.pt、key_texts.json、fact_memory.json、fact_spans.pt、fact_gate.json。

研究专家的 fact_memory.json 是事实列表，桌面不把它当成显式记忆。
新专家把实体、事实和来源对话写成对象，路由和边界守卫读这份表。
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


def _scoped_fact_id(expert_name: str, existing: str, index: int) -> str:
    """每个专家里的 f1 不能和另一个专家的 f1 撞车，否则按编号纠正会改错人。"""
    existing = (existing or "").strip()
    prefix = f"{expert_name}-"
    if existing.startswith(prefix):
        return existing
    if existing:
        return f"{prefix}{existing}"
    return f"{prefix}f{index + 1}"


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
        # 研究仓库把事实 τ 写在 tau 上，并带 reranker。那份文件不抬高桌面的路由阈值。
        if "reranker" in data and "fact_tau" not in data:
            return defaults
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
    fact_bank: Any = None

    def public_dict(self) -> dict[str, Any]:
        facts = []
        if self.fact_memory:
            for index, fact in enumerate(self.fact_memory.get("facts", [])):
                qa = fact.get("qa") or []
                facts.append({
                    "id": fact.get("id") or f"{self.name}#{index}",
                    "statement": fact.get("statement", ""),
                    "entity": fact.get("entity", ""),
                    "attr": fact.get("attr", ""),
                    "value": fact.get("value", ""),
                    "question": qa[0]["q"] if qa else fact.get("question", ""),
                    "answer": qa[0]["a"] if qa else fact.get("value", ""),
                    "superseded": bool(fact.get("superseded")),
                    "superseded_by": fact.get("superseded_by") or "",
                    "source_conversations": fact.get("source_conversations") or [],
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
            "n_facts": len([fact for fact in facts if not fact.get("superseded")]) if self.fact_memory else (self.n_facts or len(facts)),
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


def _facts_from_legacy_list(rows: list) -> list[dict]:
    """旧的事实列表保留原来的实体名，属性按现在的句式补齐。"""
    from memory_core.extract import refresh_stored_fact

    facts = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        entity = str(row.get("entity") or "").strip()
        value = str(row.get("value") or "").strip()
        if not entity or not value:
            continue
        statement = str(row.get("statement") or "").strip()
        questions = row.get("questions") if isinstance(row.get("questions"), list) else []
        facts.append(refresh_stored_fact({
            "entity": entity,
            "attr": str(row.get("attr") or "事实"),
            "value": value,
            "statement": statement or f"{entity}的事实是{value}。",
            "question": questions[0] if questions else "",
            "answer": value,
        }))
    return facts


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
    loaded = json.loads(memory_path.read_text(encoding="utf-8")) if memory_path.is_file() else None
    # 研究评测把事实写成列表。那份文件留给 eval，桌面仍按 key_texts 走最大相似度。
    if isinstance(loaded, dict):
        from memory_core.extract import refresh_stored_fact

        fact_memory = dict(loaded)
        fact_memory["facts"] = [
            refresh_stored_fact(fact) if isinstance(fact, dict) else fact
            for fact in loaded.get("facts") or []
        ]
        explicit = True
        entities = [str(item) for item in fact_memory.get("entities", []) if str(item).strip()]
        sources = list(fact_memory.get("source_conversations") or [])
        display = fact_memory.get("display_name") or _display_name(entities, name)
    elif isinstance(loaded, list):
        # 0.1.x 和研究评测把事实写成列表。转成可回答的事实，名册仍只用来做旧路由。
        # 对不上已保存的事实时提示重新巩固，不把多出来的实体写进守卫。
        facts = _facts_from_legacy_list(loaded)
        texts_path = directory / "key_texts.json"
        texts = json.loads(texts_path.read_text(encoding="utf-8")) if texts_path.is_file() else []
        entities = extract_entities_from_key_texts(texts)
        if facts:
            fact_memory = {"facts": facts, "entities": list(entities), "legacy": True}
        display = _display_name(entities, name)
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
    """只登记干净的实体名。

    「沈星河最喜欢」「沈星河住在哪里」这类把修饰词吞进名字的写法不进名册，
    否则「喜」会被当成名字的一部分，守卫对不上「沈星河喜欢喝什么茶？」。
    问句里抽出的名字只有在规范化之后等于已登记实体时才算别名，并且仍只保留干净写法。
    """
    ensure_scripts_path()
    from router import canonicalize_entity, entity_key, extract_query_entity

    cleaned: list[str] = []
    seen: set[str] = set()

    def accept(name: str) -> None:
        key = entity_key(name)
        canon = canonicalize_entity(name)
        if not key or not canon or len(canon) < 2 or key in seen:
            return
        seen.add(key)
        if re_cjk(canon):
            cleaned.append(canon)
        else:
            cleaned.append(canon)

    def re_cjk(text: str) -> bool:
        return any("\u4e00" <= char <= "\u9fff" for char in text)

    for entity in entities:
        accept(str(entity or ""))
    for text in texts or []:
        found = extract_query_entity(str(text))
        if not found:
            continue
        key = entity_key(found)
        if key and key in seen:
            continue
        # 问句里的新名字不是这条事实的实体，不另登记。
    return cleaned


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
    stored: list[dict] = []
    for index, fact in enumerate(facts):
        item = dict(fact)
        item["id"] = _scoped_fact_id(name, str(item.get("id") or ""), index)
        if not item.get("source_conversations"):
            item["source_conversations"] = sources
        stored.append(item)
    active = [fact for fact in stored if not fact.get("superseded")]
    if not active:
        raise RuntimeError("没有可登记的事实")
    if len(active) != len(stored):
        key_texts = []
        for fact in active:
            if fact.get("statement"):
                key_texts.append(str(fact["statement"]))
            for qa in fact.get("qa") or []:
                if qa.get("q"):
                    key_texts.append(str(qa["q"]))
        ensure_scripts_path()
        from router import embed

        key = embed(key_texts)
    torch.save(key.cpu(), expert_dir / "router_key.pt")
    (expert_dir / "key_texts.json").write_text(json.dumps(key_texts, ensure_ascii=False), encoding="utf-8")
    alias_texts = list(key_texts)
    for fact in active:
        alias_texts.append(str(fact.get("statement") or ""))
        for qa in fact.get("qa") or []:
            alias_texts.append(str(qa.get("q") or ""))
    entities = guard_entity_aliases(entities, alias_texts)
    memory = {
        "expert": name,
        "display_name": display_name,
        "entities": entities,
        "source_conversations": sources,
        "facts": stored,
    }
    (expert_dir / "fact_memory.json").write_text(json.dumps(memory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    from memory_core.fact_span import build_fact_bank, save_fact_bank

    bank = build_fact_bank(active)
    if bank is not None:
        save_fact_bank(expert_dir / "fact_spans.pt", bank)
    ensure_gate_file(experts_dir)
    entry = {
        "expert": name,
        "batch": batch,
        "n_facts": len(active),
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

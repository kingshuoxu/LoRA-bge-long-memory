"""按事实比较问句，而不是按整个人。

和已合并的事实语义闸同一套做法：比较前把在册实体换成「某」，把取值换成「某值」。
每条事实单独存它的问句/陈述向量和属性短语向量。问句要达到校准过的 τ，
并且不能更像另一条事实；同时还要够接近这条事实自己的属性短语。
同一人没写过的属性因此回基座。这里不按关键词或属性名词表拦截。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import torch

from memory_core.paths import ensure_scripts_path

CALIBRATED_TAU = 0.622
MASK = "某"
VALUE_MASK = "某值"


def semantic_tau(gate: dict | None) -> float:
    """事实语义闸的阈值。旧包把 fact_tau 写成 0.6，那是路由键的读取阈值，不够用。"""
    if not gate:
        return CALIBRATED_TAU
    try:
        value = float(gate.get("fact_tau", CALIBRATED_TAU))
    except (TypeError, ValueError):
        return CALIBRATED_TAU
    if value <= 0.6:
        return CALIBRATED_TAU
    return value


def mask_fact(text: str, entity: str, value: str, mask: str = MASK, value_mask: str = VALUE_MASK) -> str:
    value = str(value or "").rstrip("年")
    pieces = []
    if entity:
        pieces.append((entity, mask))
    if value:
        pieces.append((value, value_mask))
    for src, dst in sorted(pieces, key=lambda item: len(item[0]), reverse=True):
        text = text.replace(src, dst)
    return text


def mask_query(query: str, entities: list[str], mask: str = MASK) -> str:
    for name in sorted({entity for entity in entities if entity}, key=len, reverse=True):
        if name in query:
            query = query.replace(name, mask)
    return query


def _fact_value(fact: dict) -> str:
    value = str(fact.get("value") or fact.get("answer") or "").strip()
    if value:
        return value
    for qa in fact.get("qa") or []:
        answer = str(qa.get("a") or "").strip()
        if answer:
            return answer
    return ""


def _masked_fact_texts(fact: dict) -> list[str]:
    entity = str(fact.get("entity") or "").strip()
    value = _fact_value(fact)
    raws: list[str] = []
    if fact.get("statement"):
        raws.append(str(fact["statement"]))
    for qa in fact.get("qa") or []:
        if qa.get("q"):
            raws.append(str(qa["q"]))
    if fact.get("question"):
        raws.append(str(fact["question"]))
    seen: set[str] = set()
    texts: list[str] = []
    for raw in raws:
        text = mask_fact(raw, entity, value).strip()
        if text and text not in seen:
            seen.add(text)
            texts.append(text)
    return texts


@dataclass
class FactBank:
    entities: list[str]
    question_vecs: torch.Tensor
    question_owner: torch.Tensor
    attr_vecs: torch.Tensor
    attrs: list[str]

    @property
    def n_facts(self) -> int:
        return len(self.attrs)

    def allows(self, query: str, tau: float = CALIBRATED_TAU) -> tuple[bool, float, str]:
        """问句是否对得上某一条已存事实。

        返回 (对得上, 最像的那条事实的问句相似度, 那条事实的属性名)。
        对得上要求：问句相似度 ≥ τ，且不低于其他不同事实，属性短语相似度也 ≥ τ。
        """
        if self.n_facts == 0 or self.question_vecs.numel() == 0:
            return False, 0.0, ""
        ensure_scripts_path()
        from router import embed

        query_vec = embed([mask_query(query, self.entities)])[0]
        owns: list[float] = []
        for index in range(self.n_facts):
            chosen = self.question_owner == index
            owns.append(float((self.question_vecs[chosen] @ query_vec).max()))
        best = max(range(self.n_facts), key=lambda index: owns[index])
        best_block = self.question_vecs[self.question_owner == best]
        duplicated = (self.question_vecs @ best_block.T).max(dim=1).values >= 0.999
        other = -1.0
        for index in range(self.n_facts):
            if index == best:
                continue
            usable = (self.question_owner == index) & ~duplicated
            if not bool(usable.any()):
                continue
            other = max(other, float((self.question_vecs[usable] @ query_vec).max()))
        own = owns[best]
        attr_score = float(self.attr_vecs[best] @ query_vec)
        ok = own >= tau and own + 1e-6 >= other and attr_score >= tau
        return ok, own, self.attrs[best] if ok else ""


def build_fact_bank(facts: list[dict]) -> FactBank | None:
    ensure_scripts_path()
    from router import embed

    entities: list[str] = []
    texts: list[str] = []
    owners: list[int] = []
    attrs: list[str] = []
    attr_sources: list[str] = []
    for fact in facts:
        masked = _masked_fact_texts(fact)
        if not masked:
            continue
        entity = str(fact.get("entity") or "").strip()
        if entity and entity not in entities:
            entities.append(entity)
        attr = str(fact.get("attr") or "").strip()
        owners.extend([len(attrs)] * len(masked))
        texts.extend(masked)
        attrs.append(attr)
        attr_sources.append(attr if attr else masked[0])
    if not texts:
        return None
    return FactBank(
        entities=entities,
        question_vecs=embed(texts).cpu(),
        question_owner=torch.tensor(owners, dtype=torch.long),
        attr_vecs=embed(attr_sources).cpu(),
        attrs=attrs,
    )


def save_fact_bank(path: Path, bank: FactBank) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "question_vecs": bank.question_vecs.cpu().float(),
            "question_owner": bank.question_owner.cpu().long(),
            "attr_vecs": bank.attr_vecs.cpu().float(),
        },
        path,
    )


def load_fact_bank(path: Path, facts: list[dict]) -> FactBank | None:
    path = Path(path)
    if not path.is_file():
        return None
    data = torch.load(path, weights_only=True)
    question_vecs = data["question_vecs"].float().cpu()
    question_owner = data["question_owner"].long().cpu()
    attr_vecs = data["attr_vecs"].float().cpu()
    attrs: list[str] = []
    entities: list[str] = []
    expected = 0
    for fact in facts:
        masked = _masked_fact_texts(fact)
        if not masked:
            continue
        entity = str(fact.get("entity") or "").strip()
        if entity and entity not in entities:
            entities.append(entity)
        attrs.append(str(fact.get("attr") or "").strip())
        expected += len(masked)
    if len(attrs) != int(attr_vecs.shape[0]) or expected != int(question_vecs.shape[0]):
        return None
    if int(question_owner.shape[0]) != expected:
        return None
    return FactBank(
        entities=entities,
        question_vecs=question_vecs,
        question_owner=question_owner,
        attr_vecs=attr_vecs,
        attrs=attrs,
    )


def ensure_fact_bank(expert) -> FactBank | None:
    """读专家目录里的 fact_spans.pt；没有就按 fact_memory 现编一份，缓存在这条记录上。"""
    if not getattr(expert, "explicit", False):
        return None
    cached = getattr(expert, "fact_bank", None)
    if cached is not None:
        return cached
    facts = []
    if expert.fact_memory:
        facts = list(expert.fact_memory.get("facts") or [])
    bank = None
    span_path = Path(expert.directory) / "fact_spans.pt"
    if span_path.is_file():
        bank = load_fact_bank(span_path, facts)
    if bank is None and facts:
        bank = build_fact_bank(facts)
    expert.fact_bank = bank
    return bank

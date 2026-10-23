"""按事实比较问句，而不是按整个人。

和已合并的事实语义闸同一套做法：比较前把在册实体换成「某」，把取值换成「某值」。
每条事实单独存它的问句/陈述向量和属性短语向量。问句要达到校准过的 τ，
并且不能更像另一条事实；同时还要够接近这条事实自己的属性短语。
同一人没写过的属性因此回基座。这里不按关键词或属性名词表拦截。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import re

import torch

from memory_core.paths import ensure_scripts_path
from memory_core.prompts import has_cjk

CALIBRATED_TAU = 0.622
# 问句和某条已存问法几乎重合时，属性短词不能再否决。
# 0.91 卡在英文「狗的名字」改写 0.926 和「别人的狗」0.891 之间。
NEAR_TAU = 0.91
# 属性线在 persona_suite 的调参分片上选定。串属性不再靠抬高这条线，
# 而由问句里的性质和事物名挡掉。训练问句几乎重合时仍走 NEAR_TAU。
ATTR_TAU_ZH = 0.45
ATTR_TAU_EN = 0.45
MASK = "某"
VALUE_MASK = "某值"


def attr_tau(query: str) -> float:
    """属性短词和问句不是同一个尺度，中英各自校准。"""
    if has_cjk(query):
        return ATTR_TAU_ZH
    return ATTR_TAU_EN


def _fold_gate_text(text: str) -> str:
    """拉丁字母忽略大小写。掩码「某」是汉字，不能靠整句是否含汉字来判断。"""
    return "".join(char.casefold() if char.isascii() else char for char in text)


def _entity_surfaces(name: str) -> list[str]:
    surfaces = []
    raw = str(name or "").strip()
    if raw:
        surfaces.append(raw)
    ensure_scripts_path()
    from router import canonicalize_entity

    canon = canonicalize_entity(raw)
    if canon and canon not in surfaces:
        surfaces.append(canon)
    return surfaces


def _mentions_self(query: str) -> bool:
    """「我」只认「我的」或后面不再接汉字。避免「我们」「告诉我」误命中用户。"""
    if "我的" in query:
        return True
    return bool(re.search(r"我(?![\u4e00-\u9fff])", query))


def entity_mentioned(name: str, query: str) -> bool:
    """问句里是否点了这个实体。拉丁名忽略大小写、称谓和所有格。"""
    if not name or not query:
        return False
    if name == "我":
        return _mentions_self(query)
    if name in query:
        return True
    ensure_scripts_path()
    from router import entity_key

    key = entity_key(name)
    if not key:
        return False
    if has_cjk(key):
        return key in query
    return key in query.casefold()


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


def _replace_surface(text: str, surface: str, mask: str) -> str:
    if not surface:
        return text
    if has_cjk(surface):
        return text.replace(surface, mask)
    pattern = re.compile(r"(?<![A-Za-z])" + re.escape(surface) + r"(?![A-Za-z])", re.IGNORECASE)
    return pattern.sub(mask, text)


def mask_fact(text: str, entity: str, value: str, mask: str = MASK, value_mask: str = VALUE_MASK) -> str:
    value = str(value or "").rstrip("年")
    pieces = []
    for surface in _entity_surfaces(entity):
        pieces.append((surface, mask))
    if value:
        pieces.append((value, value_mask))
    for src, dst in sorted(pieces, key=lambda item: len(item[0]), reverse=True):
        text = _replace_surface(text, src, dst)
    return _fold_gate_text(text)


def mask_query(query: str, entities: list[str], mask: str = MASK) -> str:
    surfaces = []
    for name in {entity for entity in entities if entity}:
        surfaces.extend(_entity_surfaces(name))
    for surface in sorted(set(surfaces), key=len, reverse=True):
        query = _replace_surface(query, surface, mask)
    return _fold_gate_text(query)


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
    for question in fact.get("gate_questions") or []:
        if question:
            raws.append(str(question))
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
    fact_entities: list[str] | None = None

    @property
    def n_facts(self) -> int:
        return len(self.attrs)

    def explain(self, query: str, tau: float = CALIBRATED_TAU, metas: list[dict] | None = None, attr_floor: float | None = None) -> dict:
        """和 allows 同一次比较，并给出每条事实的问句分、属性分。

        metas 与事实银行的下标对齐。passed 只标闸门真正接受的那条，
        以及问句向量和它几乎重合、属性分也过线的事实。
        """
        empty = {
            "matched": False,
            "best_question_sim": 0.0,
            "matched_attr": "",
            "other_question_sim": -1.0,
            "facts": [],
        }
        if self.n_facts == 0 or self.question_vecs.numel() == 0:
            return empty
        ensure_scripts_path()
        from router import embed

        names = list(self.fact_entities or [])
        if len(names) < self.n_facts:
            names.extend([""] * (self.n_facts - len(names)))
        mentioned = [index for index, name in enumerate(names) if entity_mentioned(name, query)]
        eligible = set(mentioned) if mentioned else set(range(self.n_facts))
        query_vec = embed([mask_query(query, self.entities)])[0]
        owns: list[float] = []
        attr_scores: list[float] = []
        for index in range(self.n_facts):
            chosen = self.question_owner == index
            owns.append(float((self.question_vecs[chosen] @ query_vec).max()))
            attr_scores.append(float(self.attr_vecs[index] @ query_vec))
        best = max(eligible, key=lambda index: owns[index])
        best_block = self.question_vecs[self.question_owner == best]
        duplicated = (self.question_vecs @ best_block.T).max(dim=1).values >= 0.999
        other = -1.0
        for index in eligible:
            if index == best:
                continue
            usable = (self.question_owner == index) & ~duplicated
            if not bool(usable.any()):
                continue
            other = max(other, float((self.question_vecs[usable] @ query_vec).max()))
        own = owns[best]
        floor = attr_tau(query) if attr_floor is None else float(attr_floor)
        near = own >= NEAR_TAU
        ok = own + 1e-6 >= other and (near or (own >= tau and attr_scores[best] >= floor))
        facts = []
        for index in range(self.n_facts):
            mask = self.question_owner == index
            near = index != best and bool(mask.any()) and bool(duplicated[mask].all())
            passed = bool(
                index in eligible
                and ok
                and (index == best or (near and owns[index] >= tau and attr_scores[index] >= floor))
            )
            meta = metas[index] if metas and index < len(metas) else {}
            facts.append({
                "fact_id": str(meta.get("fact_id") or ""),
                "node_id": str(meta.get("node_id") or ""),
                "statement": str(meta.get("statement") or ""),
                "entity": str(meta.get("entity") or ""),
                "attr": str(meta.get("attr") or self.attrs[index]),
                "value": str(meta.get("value") or ""),
                "question": str(meta.get("question") or ""),
                "question_sim": round(owns[index], 4),
                "attr_sim": round(attr_scores[index], 4),
                "best": index == best,
                "near_duplicate": near,
                "passed": passed,
            })
        facts.sort(key=lambda item: item["question_sim"], reverse=True)
        info = {
            "matched": ok,
            "best_question_sim": own,
            "matched_attr": self.attrs[best] if ok else "",
            "other_question_sim": other,
            "facts": facts,
        }
        from memory_core.paraphrase import adjudicate

        return adjudicate(query, info)

    def allows(self, query: str, tau: float = CALIBRATED_TAU) -> tuple[bool, float, str]:
        """问句是否对得上某一条已存事实。

        返回 (对得上, 最像的那条事实的问句相似度, 那条事实的属性名)。
        对得上要求：问句不低于其他事实，并且要么几乎重合于已存问句，要么问句和属性都过各自的阈值。
        """
        info = self.explain(query, tau)
        return info["matched"], info["best_question_sim"], info["matched_attr"]


def build_fact_bank(facts: list[dict]) -> FactBank | None:
    ensure_scripts_path()
    from router import embed

    facts = [fact for fact in facts if not fact.get("superseded")]
    entities: list[str] = []
    texts: list[str] = []
    owners: list[int] = []
    attrs: list[str] = []
    fact_entities: list[str] = []
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
        fact_entities.append(entity)
        attr_sources.append(attr if attr else masked[0])
    if not texts:
        return None
    return FactBank(
        entities=entities,
        question_vecs=embed(texts).cpu(),
        question_owner=torch.tensor(owners, dtype=torch.long),
        attr_vecs=embed(attr_sources).cpu(),
        attrs=attrs,
        fact_entities=fact_entities,
    )


def save_fact_bank(path: Path, bank: FactBank) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "question_vecs": bank.question_vecs.cpu().float(),
            "question_owner": bank.question_owner.cpu().long(),
            "attr_vecs": bank.attr_vecs.cpu().float(),
            "gate_norm": torch.tensor(1),
        },
        path,
    )


def load_fact_bank(path: Path, facts: list[dict]) -> FactBank | None:
    path = Path(path)
    if not path.is_file():
        return None
    data = torch.load(path, weights_only=True)
    latin = any(fact.get("entity") and not has_cjk(str(fact.get("entity"))) for fact in facts)
    if latin and int(data.get("gate_norm") or 0) != 1:
        return None
    question_vecs = data["question_vecs"].float().cpu()
    question_owner = data["question_owner"].long().cpu()
    attr_vecs = data["attr_vecs"].float().cpu()
    attrs: list[str] = []
    fact_entities: list[str] = []
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
        fact_entities.append(entity)
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
        fact_entities=fact_entities,
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
        facts = [fact for fact in (expert.fact_memory.get("facts") or []) if not fact.get("superseded")]
    bank = None
    span_path = Path(expert.directory) / "fact_spans.pt"
    if span_path.is_file():
        bank = load_fact_bank(span_path, facts)
    if bank is None and facts:
        bank = build_fact_bank(facts)
    expert.fact_bank = bank
    return bank

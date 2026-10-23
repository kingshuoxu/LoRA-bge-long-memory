"""读取路由。

研究评测脚本仍用「最大相似度 + verify_entity_guard」。这里在同一套函数上增加：
- 实体优先：问句里出现某个新专家登记过的实体时，先考虑那个专家；
- 边界守卫：直接调用 scripts/router.py 的 verify_entity_guard，删除后的问句不能落到别的专家；
- 事实闸：带 fact_memory 的新专家按每条事实的问句向量和属性向量做语义比较，
  没有对上的属性就回基座。没有 fact_memory 的旧专家不走这一关。

不改 embed / verify_entity_guard 的签名。bge 目录由调用方写到 router.EMB_MODEL（绝对路径），
研究脚本自己的进程仍使用原来的相对路径。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from memory_core.fact_span import ensure_fact_bank, semantic_tau
from memory_core.paths import ensure_scripts_path
from memory_core.store import ExpertRecord, load_gate


@dataclass
class RouteDecision:
    fired: bool
    expert: str | None
    sim: float
    label: str
    reason: str
    entity_pass: bool
    fact_pass: bool

    def public_dict(self) -> dict:
        return {
            "fired": self.fired,
            "expert": self.expert,
            "sim": round(self.sim, 4),
            "label": self.label,
            "reason": self.reason,
            "entity_pass": self.entity_pass,
            "fact_pass": self.fact_pass,
        }


def bind_bge(models_dir: Path) -> None:
    ensure_scripts_path()
    import router

    router.EMB_MODEL = str(Path(models_dir) / "bge-small-zh-v1.5")


def _base(sim: float, expert: str | None, reason: str, entity_pass: bool, fact_pass: bool) -> RouteDecision:
    return RouteDecision(
        fired=False,
        expert=expert,
        sim=sim,
        label="基座",
        reason=reason,
        entity_pass=entity_pass,
        fact_pass=fact_pass,
    )


def _entity_hit(entity: str, text: str) -> int:
    """命中时返回用来比长短的长度。拉丁名忽略大小写和称谓。"""
    if len(entity) >= 2 and entity in text:
        return len(entity)
    ensure_scripts_path()
    from router import entity_key

    key = entity_key(entity)
    if not key or any("\u4e00" <= char <= "\u9fff" for char in key):
        return 0
    if key in text.casefold():
        return len(key)
    return 0


def _owner(text: str, experts: list[ExpertRecord]) -> ExpertRecord | None:
    best: tuple[int, ExpertRecord] | None = None
    for expert in experts:
        for entity in expert.entities:
            length = _entity_hit(entity, text)
            if length >= 2 and (best is None or length > best[0]):
                best = (length, expert)
    return None if best is None else best[1]


def _canonical_entities(expert: ExpertRecord) -> list[str]:
    names: list[str] = []
    memory = expert.fact_memory or {}
    for fact in memory.get("facts") or []:
        entity = str(fact.get("entity") or "").strip()
        if len(entity) >= 2 and entity not in names:
            names.append(entity)
    return names


def _guard(expert: ExpertRecord, text: str) -> bool:
    ensure_scripts_path()
    from router import extract_query_entity, verify_entity_guard

    if expert.explicit and not expert.entities:
        return False
    if verify_entity_guard(text, expert.entities):
        return True
    if not expert.explicit:
        return False
    # scripts/router.py 会把「那辆」「养的」吞进实体名，训练问句里没出现过的写法
    # 就不在别名册里。只要抽出的名字仍以这条事实的实体开头，先交给事实闸，不在这里拒掉。
    found = extract_query_entity(text)
    if not found:
        return False
    return any(found.startswith(entity) and len(found) > len(entity) for entity in _canonical_entities(expert))


def _legacy_decision(text: str, pool: list[ExpertRecord], sims: dict[str, float], tau: float) -> RouteDecision:
    best = max(pool, key=lambda expert: sims[expert.name])
    sim = sims[best.name]
    entity_pass = _guard(best, text)
    if sim >= tau and entity_pass:
        return RouteDecision(
            fired=True,
            expert=best.name,
            sim=sim,
            label=f"记忆 · {best.display_name}",
            reason="max_sim",
            entity_pass=True,
            fact_pass=True,
        )
    why = "below_tau" if sim < tau else "boundary_guard"
    return _base(sim, best.name, why, entity_pass, True)


RECALL_WORDING = "亮起的星表示这次路由和事实闸对上了这些事实。LoRA 是整份专家一起挂上的，不是每颗星各有一份权重。"

_REASON_TEXT = {
    "entity_first": "问句点名了这个专家登记过的实体",
    "max_sim": "在参与比较的专家里，路由键相似度最高",
    "fact_gate": "事实闸没有对上任何已存事实，回答走基座",
    "below_tau": "路由键相似度低于阈值，回答走基座",
    "boundary_guard": "边界守卫没有通过，回答走基座",
    "no_experts": "没有可挂载的专家，回答走基座",
    "missing_weights": "专家权重不在，这一轮没有挂载，回答走基座",
    "correction_proposal": "这一轮在确认纠正，没有挂载专家",
}


def _round(value: float) -> float:
    return round(float(value), 4)


def _gate_metas(expert: ExpertRecord) -> list[dict]:
    from memory_core.fact_span import _masked_fact_texts

    facts = list((expert.fact_memory or {}).get("facts") or [])
    metas = []
    for index, fact in enumerate(facts):
        if fact.get("superseded"):
            continue
        if not _masked_fact_texts(fact):
            continue
        fact_id = str(fact.get("id") or f"{expert.name}#{index}")
        qa = fact.get("qa") or []
        metas.append({
            "fact_id": fact_id,
            "node_id": f"fact:{fact_id}",
            "statement": fact.get("statement") or "",
            "entity": fact.get("entity") or "",
            "attr": fact.get("attr") or "",
            "value": fact.get("value") or fact.get("answer") or "",
            "question": qa[0]["q"] if qa else fact.get("question") or "",
        })
    return metas


def _explicit_decision(
    expert: ExpertRecord,
    text: str,
    tau: float,
    reason: str,
    model=None,
    tok=None,
    device=None,
) -> tuple[RouteDecision, dict]:
    """点名了新专家之后，只有某条已存事实对得上这句问话才挂载。"""
    entity_pass = _guard(expert, text)
    gate_view = {
        "applied": True,
        "expert": expert.name,
        "tau": _round(tau),
        "entity_pass": entity_pass,
        "matched": False,
        "facts": [],
    }
    if not entity_pass:
        return _base(0.0, expert.name, "boundary_guard", False, False), gate_view
    bank = ensure_fact_bank(expert)
    if bank is None:
        gate_view["applied"] = False
        gate_view["why"] = "没有事实向量，不能逐条比较"
        return _base(0.0, expert.name, "fact_gate", True, False), gate_view
    metas = _gate_metas(expert)
    if len(metas) != bank.n_facts:
        metas = [
            {
                "fact_id": "",
                "node_id": "",
                "statement": "",
                "entity": "",
                "attr": bank.attrs[index] if index < len(bank.attrs) else "",
                "value": "",
                "question": "",
            }
            for index in range(bank.n_facts)
        ]
    info = bank.explain(text, tau, metas)
    if not info["matched"]:
        from memory_core.paraphrase import polar_question

        alt = polar_question(text)
        if alt and alt != text:
            alt_info = bank.explain(alt, tau, metas)
            if alt_info.get("matched"):
                alt_info = dict(alt_info)
                alt_info["polar_of"] = text
                info = alt_info
    if not info["matched"] and model is not None:
        from memory_core.paraphrase import rescue_near_miss

        info = rescue_near_miss(text, bank, tau, info, model, tok, device)
    if not info["matched"] and model is not None:
        from memory_core.paraphrase import confirm_stored_answer

        info = confirm_stored_answer(text, info, model, tok, device)
    from memory_core.paraphrase import adjudicate

    info = adjudicate(text, info)
    gate_view["matched"] = bool(info["matched"])
    gate_view["facts"] = info["facts"]
    if info.get("rejected_attribute"):
        gate_view["rejected_attribute"] = True
    # 属性已经对上才把记住的取值交回去。问错属性的命中在上面被撤掉。
    if info.get("matched"):
        gate_view["answer_from_fact"] = True
    if info["matched"]:
        return RouteDecision(
            fired=True,
            expert=expert.name,
            sim=info["best_question_sim"],
            label=f"记忆 · {expert.display_name}",
            reason=reason,
            entity_pass=True,
            fact_pass=True,
        ), gate_view
    return _base(info["best_question_sim"], expert.name, "fact_gate", True, False), gate_view


def _key_row_text(expert: ExpertRecord, index: int) -> str:
    path = Path(expert.directory) / "key_texts.json"
    if not path.is_file():
        return ""
    try:
        texts = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if not isinstance(texts, list) or index >= len(texts) or index >= int(expert.key.shape[0]):
        return ""
    text = texts[index]
    return text if isinstance(text, str) else ""


def _blank_trace(reason: str) -> dict:
    return {
        "fired": False,
        "abstain": True,
        "mounted": False,
        "reason": reason,
        "reason_text": _REASON_TEXT.get(reason, reason),
        "expert": None,
        "mounted_expert": None,
        "mounted_label": "基座",
        "sim": 0.0,
        "thresholds": {},
        "experts": [],
        "fact_gate": None,
        "matched_facts": [],
        "wording": RECALL_WORDING,
    }


def route_with_trace(
    text: str,
    experts: list[ExpertRecord],
    gate: dict[str, float] | None = None,
    model=None,
    tok=None,
    device=None,
) -> tuple[RouteDecision, dict]:
    """和 route_text 同一次计算。trace 是界面点亮星云用的分数，不另做一套判定。"""
    gate = gate or {"tau": 0.6, "fact_tau": 0.622}
    tau = float(gate.get("tau", 0.6))
    fact_tau = semantic_tau(gate)
    if not experts:
        return _base(0.0, None, "no_experts", False, False), _blank_trace("no_experts")
    ensure_scripts_path()
    from router import embed

    query = embed([text])[0]
    sims: dict[str, float] = {}
    rows: dict[str, dict] = {}
    for expert in experts:
        scores = expert.key @ query
        sim = float(scores.max().item())
        best_row = int(scores.argmax().item())
        sims[expert.name] = sim
        rows[expert.name] = {
            "name": expert.name,
            "display_name": expert.display_name,
            "sim": _round(sim),
            "explicit": bool(expert.explicit),
            "considered": False,
            "chosen": False,
            "best_key_index": best_row,
            "best_key_text": _key_row_text(expert, best_row),
        }
    explicit = [expert for expert in experts if expert.explicit]
    legacy = [expert for expert in experts if not expert.explicit]
    owner = _owner(text, explicit)
    fact_gate = None
    if owner is not None:
        rows[owner.name]["considered"] = True
        decision, fact_gate = _explicit_decision(owner, text, fact_tau, "entity_first", model, tok, device)
    elif legacy:
        for expert in legacy:
            rows[expert.name]["considered"] = True
        decision = _legacy_decision(text, legacy, sims, tau)
        if decision.expert and decision.expert in rows:
            fact_gate = {
                "applied": False,
                "expert": decision.expert,
                "tau": _round(fact_tau),
                "matched": False,
                "facts": [],
                "why": "这位专家没有逐条事实向量，只比较了路由键",
            }
    elif explicit:
        for expert in explicit:
            rows[expert.name]["considered"] = True
        best = max(explicit, key=lambda expert: sims[expert.name])
        decision, fact_gate = _explicit_decision(best, text, fact_tau, "max_sim", model, tok, device)
    else:
        decision = _base(0.0, None, "no_experts", False, False)
    if decision.fired and decision.expert in rows:
        rows[decision.expert]["chosen"] = True
    matched = [fact for fact in (fact_gate or {}).get("facts") or [] if fact.get("passed")]
    trace = {
        "fired": decision.fired,
        "abstain": not decision.fired,
        "mounted": decision.fired,
        "reason": decision.reason,
        "reason_text": _REASON_TEXT.get(decision.reason, decision.reason),
        "expert": decision.expert,
        "mounted_expert": decision.expert if decision.fired else None,
        "mounted_label": decision.label,
        "sim": _round(decision.sim),
        "thresholds": {"router_tau": _round(tau), "fact_tau": _round(fact_tau)},
        "experts": sorted(rows.values(), key=lambda item: item["sim"], reverse=True),
        "fact_gate": fact_gate,
        "matched_facts": matched if decision.fired else [],
        "wording": RECALL_WORDING,
    }
    return decision, trace


def route_text(
    text: str,
    experts: list[ExpertRecord],
    gate: dict[str, float] | None = None,
    model=None,
    tok=None,
    device=None,
) -> RouteDecision:
    decision, _trace = route_with_trace(text, experts, gate, model, tok, device)
    return decision


def legacy_top1(text: str, experts: list[ExpertRecord], tau: float = 0.6) -> tuple[str, float, bool, bool]:
    """与 scripts/eval_memory.py 相同的判定，用来对照旧专家结果没有被改写。"""
    ensure_scripts_path()
    from router import embed, verify_entity_guard

    query = embed([text])[0]
    sims = {expert.name: float((expert.key @ query).max().item()) for expert in experts}
    best = max(experts, key=lambda expert: sims[expert.name])
    entity_pass = bool(verify_entity_guard(text, best.entities))
    sim = sims[best.name]
    fired = sim >= tau and entity_pass
    return best.name, sim, fired, entity_pass


def load_merged_gate(dirs: list[Path]) -> dict[str, float]:
    gate = {"tau": 0.6, "fact_tau": 0.622, "dedup_sim": 0.94, "skip_loss": 2.5}
    for directory in dirs:
        if directory and Path(directory).is_dir():
            loaded = load_gate(Path(directory))
            gate.update(loaded)
    gate["fact_tau"] = semantic_tau(gate)
    return gate

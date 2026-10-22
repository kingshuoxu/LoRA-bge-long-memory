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


def _owner(text: str, experts: list[ExpertRecord]) -> ExpertRecord | None:
    best: tuple[int, ExpertRecord] | None = None
    for expert in experts:
        for entity in expert.entities:
            if len(entity) >= 2 and entity in text:
                if best is None or len(entity) > best[0]:
                    best = (len(entity), expert)
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


def _explicit_decision(expert: ExpertRecord, text: str, tau: float, reason: str) -> RouteDecision:
    """点名了新专家之后，只有某条已存事实对得上这句问话才挂载。"""
    entity_pass = _guard(expert, text)
    if not entity_pass:
        return _base(0.0, expert.name, "boundary_guard", False, False)
    bank = ensure_fact_bank(expert)
    if bank is None:
        return _base(0.0, expert.name, "fact_gate", True, False)
    matched, score, _attr = bank.allows(text, tau)
    if matched:
        return RouteDecision(
            fired=True,
            expert=expert.name,
            sim=score,
            label=f"记忆 · {expert.display_name}",
            reason=reason,
            entity_pass=True,
            fact_pass=True,
        )
    return _base(score, expert.name, "fact_gate", True, False)


def route_text(text: str, experts: list[ExpertRecord], gate: dict[str, float] | None = None) -> RouteDecision:
    gate = gate or {"tau": 0.6, "fact_tau": 0.622}
    if not experts:
        return _base(0.0, None, "no_experts", False, False)
    ensure_scripts_path()
    from router import embed

    query = embed([text])[0]
    sims = {expert.name: float((expert.key @ query).max().item()) for expert in experts}
    explicit = [expert for expert in experts if expert.explicit]
    legacy = [expert for expert in experts if not expert.explicit]
    # 只有带 fact_memory 的新专家走实体优先。旧研究专家仍是「最大相似度 + 边界守卫」，
    # 这样 scripts/eval_memory.py 的判定不会被桌面路由改写。
    owner = _owner(text, explicit)
    tau = float(gate.get("tau", 0.6))
    fact_tau = semantic_tau(gate)

    # 问句点名了某个已登记实体，就只考虑那个专家。事实对不上则回基座，
    # 不再改挂相似度更高的其他专家（避免删除后的交叉误射）。
    if owner is not None:
        return _explicit_decision(owner, text, fact_tau, "entity_first")
    # 没点名新专家时，不让新专家的路由键参与 top-1，免得盖过原来的五个专家。
    if legacy:
        return _legacy_decision(text, legacy, sims, tau)
    if explicit:
        best = max(explicit, key=lambda expert: sims[expert.name])
        return _explicit_decision(best, text, fact_tau, "max_sim")
    return _base(0.0, None, "no_experts", False, False)


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

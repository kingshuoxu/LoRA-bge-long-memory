"""读取路由。

研究评测脚本仍用「最大相似度 + verify_entity_guard」。这里在同一套函数上增加：
- 实体优先：问句里出现某个专家登记过的实体时，先考虑那个专家；
- 边界守卫：直接调用 scripts/router.py 的 verify_entity_guard，删除后的问句不能落到别的专家；
- 事实门：新专家还要和 fact_memory 的路由键达到 fact_tau。没有 fact_memory 的旧专家不额外加这一关。

不改 embed / verify_entity_guard 的签名。bge 目录由调用方写到 router.EMB_MODEL（绝对路径），
研究脚本自己的进程仍使用原来的相对路径。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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


def _guard(expert: ExpertRecord, text: str) -> bool:
    ensure_scripts_path()
    from router import verify_entity_guard

    if expert.explicit and not expert.entities:
        return False
    return bool(verify_entity_guard(text, expert.entities))


def route_text(text: str, experts: list[ExpertRecord], gate: dict[str, float] | None = None) -> RouteDecision:
    gate = gate or {"tau": 0.6, "fact_tau": 0.6}
    if not experts:
        return _base(0.0, None, "no_experts", False, False)
    ensure_scripts_path()
    from router import embed

    query = embed([text])[0]
    sims = {expert.name: float((expert.key @ query).max().item()) for expert in experts}
    best = max(experts, key=lambda expert: sims[expert.name])
    # 只有带 fact_memory 的新专家走实体优先。旧研究专家仍是「最大相似度 + 边界守卫」，
    # 这样 scripts/eval_memory.py 的判定不会被桌面路由改写。
    owner = _owner(text, [expert for expert in experts if expert.explicit])
    tau = float(gate["tau"])
    fact_tau = float(gate.get("fact_tau", tau))

    def decide(expert: ExpertRecord, reason: str) -> RouteDecision:
        sim = sims[expert.name]
        entity_pass = _guard(expert, text)
        fact_pass = not (expert.explicit and sim < fact_tau)
        if sim >= tau and entity_pass and fact_pass:
            return RouteDecision(
                fired=True,
                expert=expert.name,
                sim=sim,
                label=f"记忆 · {expert.display_name}",
                reason=reason,
                entity_pass=True,
                fact_pass=True,
            )
        if sim < tau:
            why = "below_tau"
        elif not entity_pass:
            why = "boundary_guard"
        else:
            why = "fact_gate"
        return _base(sim, expert.name, why, entity_pass, fact_pass)

    # 实体优先：问句点名了某个已登记实体，就只考虑那个专家。不合格则回基座，
    # 不再改挂相似度更高的其他专家（避免删除后的交叉误射）。
    if owner is not None:
        return decide(owner, "entity_first")
    return decide(best, "max_sim")


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
    gate = {"tau": 0.6, "fact_tau": 0.6, "dedup_sim": 0.94, "skip_loss": 2.5}
    for directory in dirs:
        if directory and Path(directory).is_dir():
            loaded = load_gate(Path(directory))
            gate.update(loaded)
    return gate

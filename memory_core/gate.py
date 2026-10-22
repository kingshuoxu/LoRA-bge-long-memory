"""写入门：bge 去重 + 基座自答。阈值与 scripts/auto_write.py 相同。"""
from __future__ import annotations

from typing import Any

from memory_core.paths import ensure_scripts_path

READ_TAU = 0.6
# 事实语义闸的校准值，和 experts/fact_gate.json（PR #2）里的 τ 相同。
# 0.6 只是路由键的读取阈值，盖不住同一人没写过的属性。
FACT_TAU = 0.622
DEDUP_SIM = 0.94
SKIP_LOSS = 2.5


def fact_gate_config() -> dict[str, float]:
    return {
        "tau": READ_TAU,
        "fact_tau": FACT_TAU,
        "dedup_sim": DEDUP_SIM,
        "skip_loss": SKIP_LOSS,
    }


def keep_for_training(fact: dict[str, Any]) -> bool:
    """写门跳过的事实不进训练集，也不进路由键和事实向量。界面上再勾选也带不回来。"""
    if str(fact.get("gate") or "").startswith("skip_"):
        return False
    return bool(fact.get("selected", True))


def apply_write_gate(facts: list[dict[str, Any]], expert_keys: list, model=None, tok=None, device=None) -> list[dict[str, Any]]:
    """给每条候选加上 gate / selected。已知或重复的默认不勾选，界面上仍可改。"""
    if not facts:
        return []
    ensure_scripts_path()
    from router import embed

    vectors = embed([fact["statement"] for fact in facts])
    norm = None
    self_answer = None
    if model is not None and tok is not None and device is not None:
        from calibrate_qa_gate import _norm, self_answer as _self_answer

        norm = _norm
        self_answer = _self_answer
    for fact, vector in zip(facts, vectors):
        sim = 0.0
        if expert_keys:
            sim = max(float((key @ vector).max()) for key in expert_keys)
        fact["sim_to_memory"] = round(sim, 4)
        if sim >= DEDUP_SIM:
            fact["gate"] = "skip_duplicate"
            fact["gate_reason"] = "和已有记忆太像，写门建议跳过"
            fact["selected"] = False
            continue
        if self_answer is not None:
            ctx = model.disable_adapter() if hasattr(model, "disable_adapter") else _nullctx()
            with ctx:
                answer = self_answer(model, tok, device, fact["question"])
            gold = norm(str(fact["answer"]).rstrip("年"))
            if gold and gold in norm(answer):
                fact["gate"] = "skip_known"
                fact["gate_reason"] = f"基座已经答对（{answer[:40]}），写门建议跳过"
                fact["selected"] = False
                fact["base_answer"] = answer[:80]
                continue
            fact["base_answer"] = answer[:80]
        fact["gate"] = "write"
        fact["gate_reason"] = ""
        fact["selected"] = True
    return facts


class _nullctx:
    def __enter__(self):
        return None

    def __exit__(self, *args):
        return False

"""Model-free authority for confirmed corrections, including while training.

Only named corrected subjects (or explicit self questions) enter this path.
It reads current facts, not conversation snippets, document retrieval or adapters.
"""
from __future__ import annotations

import re
import copy
from types import SimpleNamespace

from memory_core.correction_store import active_corrections
from memory_core.prompts import has_cjk


# A timeline of beliefs/reports is not evidence of a timeline of real states.
# Scope this guard to the historical clause, so an explicit past state can still
# be followed by "now I know ...". Ambiguous sources default to correction.
_HISTORY_REPORT = re.compile(
    r"以为|认为|觉得|相信|听说|据说|听闻|记得|印象|猜|推测|估计|记录|记载|资料|"
    r"\b(?:think|thought|believ(?:e|ed)|assum(?:e|ed)|suppos(?:e|ed)|"
    r"guess(?:ed)?|suspect(?:ed)?|understood|remember(?:ed)?|heard|told|"
    r"report(?:ed|s)?|record(?:ed|s)?|apparently|allegedly)\b",
    re.I,
)
_HISTORY_FRAME = re.compile(
    r"(?:以前|过去|原来).*?(?P<zh_now>现在|如今|搬到)|"
    r"\b(?:used to|previously|formerly)\b.*?\b(?P<en_now>now)\b",
    re.I,
)
_CORRECTION_MARKER = re.compile(
    r"错|纠正|更正|不对|从未|从来没|从没|从不|never|incorrect|mistak|wrong|"
    r"correct(?:ed|ion)|\bnot\b", re.I,
)


def correction_kind(source: str, old: str, new: str) -> str:
    # Never infer a true historical state merely from the superseded row.
    if not old or not new or old == new or _CORRECTION_MARKER.search(source):
        return "correction"
    frame = _HISTORY_FRAME.search(source)
    if frame is None:
        return "correction"
    transition = frame.start("zh_now") if frame.group("zh_now") else frame.start("en_now")
    historical, current = source[:transition], source[transition:]
    if old in historical and new in current and not _HISTORY_REPORT.search(historical):
        return "state_change"
    return "correction"


def confirmed_reply(home, content: str, records: list) -> dict | None:
    from memory_core.correct import utterance_is_question
    from memory_core.fact_span import entity_mentioned
    from memory_core.grounding import _pick_fact, open_entity_question, resolve_stored_reply
    from memory_core.self_query import self_ask, self_reply

    rows = active_corrections(home)
    if not rows:
        return None
    asked_self = self_ask(content)
    related = []
    for row in rows:
        fact = row["new_fact"]
        entity = str(fact.get("entity") or "")
        is_self = entity in {"我", "用户", "I", "me"}
        if (is_self and asked_self and asked_self != "assistant") or (
            not is_self and entity and entity_mentioned(entity, re.sub(re.escape(entity) + r"(?:以前|曾经|过去|原来)", entity, content))
        ):
            related.append(row)
    if not related or not (utterance_is_question(content) or asked_self or any(
        open_entity_question(content, str(row["new_fact"].get("entity") or "")) for row in related
    )):
        return None
    # A direct ledger fallback keeps a committed correction available even if
    # an interrupted adapter registration temporarily removed its directory.
    records = records() if callable(records) else records
    by_name = {r.name: r for r in records}
    for row in related:
        if row["expert"] not in by_name:
            facts = [r["new_fact"] for r in rows if r["expert"] == row["expert"]]
            by_name[row["expert"]] = SimpleNamespace(
                name=row["expert"], display_name=row["new_fact"].get("entity") or row["expert"],
                facts=facts, fact_memory={"facts": facts}, explicit=True,
                entities=[f.get("entity") for f in facts], sources=[],
            )
    # Another expert or a re-consolidated document can still contain the same
    # superseded predicate. It is not a competing current source of truth.
    authoritative = {}
    for row in related:
        fact = row["new_fact"]
        authoritative[(str(fact.get("entity") or "").casefold(), str(fact.get("attr") or "").casefold())] = row
    experts = []
    for record in by_name.values():
        record = copy.copy(record)
        memory = dict(record.fact_memory or {})
        facts = []
        for fact in memory.get("facts") or []:
            key = (str(fact.get("entity") or "").casefold(), str(fact.get("attr") or "").casefold())
            winner = authoritative.get(key)
            if winner and fact.get("id") != winner["new_fact"].get("id"):
                continue
            facts.append(fact)
        record.fact_memory = {**memory, "facts": facts}
        experts.append(record)
    history = bool(re.search(r"以前|曾经|过去|原来|\b(?:previously|formerly|before|used to|ever)\b", content, re.I))
    matched = _pick_fact(content, [r["new_fact"] for r in related])
    if history and matched is not None:
        row = next(r for r in related if r["new_fact"] is matched)
        old = row["old_fact"].get("value") or ""
        new = matched.get("value") or ""
        if matched.get("correction_kind") == "state_change":
            answer = f"之前是{old}，现在是{new}。" if has_cjk(content) else f"Previously {old}; now {new}."
        else:
            answer = (f"旧记录中的{old}已被纠正，不能据此认定它曾经属实。当前确认的是{new}。" if has_cjk(content)
                      else f"The old record ({old}) was corrected, not confirmed as a past fact. The current confirmed value is {new}.")
        return {"text": answer, "expert": row["expert"], "facts": [matched], "reason": "correction_history"}
    resolved = self_reply(content, experts, english=not has_cjk(content)) if asked_self and asked_self != "assistant" else resolve_stored_reply(content, experts)
    if resolved is None:
        return None
    answer, owner, facts = resolved[:3]
    return {"text": answer, "expert": owner.name if owner else related[0]["expert"], "facts": facts, "reason": "confirmed_correction"}

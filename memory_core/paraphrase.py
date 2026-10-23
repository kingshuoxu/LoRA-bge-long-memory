"""巩固时为每条事实生成几条问法，只放进事实闸，不改训练样本。

问法由本地模型现写，同一语言，必须点到实体，不能带上取值。
事实闸把这些问法当成额外的键，用来接住训练问句里没出现过的说法。
"""
from __future__ import annotations

import re
from typing import Any

from memory_core.prompts import has_cjk


def _generate(model, tok, device, prompt: str, system: str) -> str:
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]
    rendered = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tok(rendered, return_tensors="pt")
    inputs = {key: value.to(device) for key, value in inputs.items()}
    ctx = model.disable_adapter() if hasattr(model, "disable_adapter") else _nullctx()
    with ctx:
        import torch

        with torch.no_grad():
            out = model.generate(
                **inputs,
                max_new_tokens=180,
                do_sample=False,
                pad_token_id=tok.eos_token_id,
            )
    return tok.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()


def _lines(text: str) -> list[str]:
    found = []
    for raw in text.splitlines():
        line = raw.strip().lstrip("-•*0123456789.、)） ").strip()
        line = line.strip("\"“”")
        if not line or line in {"无", "none", "None"}:
            continue
        if line[-1] not in "？?":
            continue
        found.append(line)
    return found


def _usable(question: str, entity: str, value: str) -> bool:
    if entity:
        if has_cjk(entity):
            if entity not in question:
                return False
        elif entity.casefold() not in question.casefold():
            return False
    if value and value.casefold() in question.casefold():
        return False
    # 是/否问句经常把模型编出来的答案写进去，例如「有铅色吗」。
    if any(mark in question for mark in ("吗", "是不是", "是否", "对不对")):
        return False
    return True


def _source_questions(fact: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for qa in fact.get("qa") or []:
        question = str(qa.get("q") or "").strip()
        if question and question not in found:
            found.append(question)
    primary = str(fact.get("question") or "").strip()
    if primary and primary not in found:
        found.insert(0, primary)
    return found[:3]


def _rewrite_prompt(question: str, entity: str, value: str) -> tuple[str, str]:
    english = not has_cjk(f"{question}{entity}{value}")
    if english:
        system = "You are a helpful assistant."
        prompt = (
            "Rewrite the question in 4 different ways.\n"
            "Each rewrite must ask for the same attribute, so the same answer still fits.\n"
            "Keep the person's name. Do not include the answer. Do not switch objects.\n"
            "Do not ask a yes/no question.\n"
            "One question per line. No numbering. No other text.\n\n"
            f"Question: {question}\n"
        )
    else:
        system = "你是助手。"
        prompt = (
            "把这个问句改写成 4 个不同的问法。\n"
            "每个改写都要问同一个属性，原来的答案也必须能回答它。\n"
            "保留人名，不要写出答案，不要换成别的事物，也不要写成是非问句。\n"
            "每行一个问句，不要编号，不要其他文字。\n\n"
            f"问句：{question}\n"
        )
    return prompt, system


def gate_questions_for_fact(fact: dict[str, Any], model, tok, device, limit: int = 8) -> list[str]:
    """按已有问句逐句改写。模型没写出合格问句时返回空列表，不拿模板充数。"""
    entity = str(fact.get("entity") or "").strip()
    value = str(fact.get("value") or fact.get("answer") or "").strip()
    if not entity:
        return []
    kept: list[str] = []
    existing = set(_source_questions(fact))
    for question in _source_questions(fact)[:2]:
        prompt, system = _rewrite_prompt(question, entity, value)
        try:
            raw = _generate(model, tok, device, prompt, system)
        except Exception:
            continue
        for line in _lines(raw):
            line = re.sub(r"\s+", " ", line).strip()
            if not _usable(line, entity, value) or line in kept or line in existing:
                continue
            kept.append(line)
            if len(kept) >= limit:
                return kept
    return kept


def _compact(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text or "", flags=re.UNICODE).casefold()


def filter_cross_fact(facts: list[dict[str, Any]], model=None, tok=None, device=None) -> None:
    """改写如果更靠近另一条事实，或答不上这条事实的取值，就拿掉。"""
    from memory_core.paths import ensure_scripts_path

    ensure_scripts_path()
    from router import embed

    owned: list[tuple[int, str]] = []
    for index, fact in enumerate(facts):
        if fact.get("superseded"):
            continue
        for question in fact.get("gate_questions") or []:
            owned.append((index, str(question)))
    if not owned:
        return
    bases: list[str] = []
    base_owner: list[int] = []
    for index, fact in enumerate(facts):
        for question in _source_questions(fact)[:4]:
            bases.append(question)
            base_owner.append(index)
    if not bases:
        return
    vectors = embed([text for _index, text in owned] + bases)
    extra = vectors[: len(owned)]
    base = vectors[len(owned) :]
    grouped: dict[int, list[str]] = {index: [] for index in range(len(facts))}
    for row, (index, text) in enumerate(owned):
        scores = extra[row] @ base.T
        own = max((float(scores[col]) for col, owner in enumerate(base_owner) if owner == index), default=-1.0)
        other = max((float(scores[col]) for col, owner in enumerate(base_owner) if owner != index), default=-1.0)
        if own + 1e-6 < other:
            continue
        # 离原问句太远的改写会把别的属性卷进来，例如把猫写成「哪种动物」。
        # 取值对得上这条事实时，可以留住稍远、但仍然忠实的说法。
        faithful = None
        if model is not None and tok is not None and device is not None and own >= 0.70:
            faithful = _value_answers(text, facts[index], model, tok, device)
        if faithful is False:
            continue
        if own < 0.80 and faithful is not True:
            continue
        compact = _compact(text)
        entity = _compact(str(facts[index].get("entity") or ""))
        bare = compact.replace(entity, "")
        if any(_compact(item).replace(entity, "") == bare for item in _source_questions(facts[index])):
            continue
        if text not in grouped[index]:
            grouped[index].append(text)
    for index, fact in enumerate(facts):
        if fact.get("superseded"):
            continue
        fact["gate_questions"] = grouped.get(index) or []


def attach_gate_questions(facts: list[dict[str, Any]], model, tok, device) -> None:
    """就地写入 fact['gate_questions']。已有的不覆盖。被取代的事实跳过。"""
    pending = [fact for fact in facts if not fact.get("superseded") and not fact.get("gate_questions")]
    for fact in pending:
        fact["gate_questions"] = gate_questions_for_fact(fact, model, tok, device)
    if pending:
        filter_cross_fact(facts, model, tok, device)


def _rewrite_query(query: str, model, tok, device) -> list[str]:
    """问句差一点没过闸时，让模型换个说法再比一次。不改事实库。"""
    english = not has_cjk(query)
    if english:
        system = "You are a helpful assistant."
        prompt = (
            "Rewrite the question in 4 different ways.\n"
            "Ask the same thing. Keep the person's name. Do not include the answer.\n"
            "Do not switch to a different topic.\n"
            "One question per line. No numbering. No other text.\n\n"
            f"Question: {query}\n"
        )
    else:
        system = "你是助手。"
        prompt = (
            "把这个问句改写成 4 个不同的问法。\n"
            "还是问同一件事，保留人名，不要写出答案，也不要改成别的话题。\n"
            "每行一个问句，不要编号，不要其他文字。\n\n"
            f"问句：{query}\n"
        )
    try:
        raw = _generate(model, tok, device, prompt, system)
    except Exception:
        return []
    kept = []
    for line in _lines(raw):
        line = re.sub(r"\s+", " ", line).strip()
        if line and line not in kept and line != query:
            kept.append(line)
    return kept[:4]


def rescue_near_miss(query: str, bank, tau: float, info: dict, model, tok, device) -> dict:
    """原问句没过闸、但已经靠近某条事实时，改写若贴上已存问句就采用。

    改写必须还是同一属性，并且和原问句仍然很像，避免把咖啡改写成茶。
    """
    from memory_core.fact_span import NEAR_TAU, entity_mentioned

    if info.get("matched") or model is None or tok is None or device is None:
        return info
    score = float(info.get("best_question_sim") or 0.0)
    if score < 0.55 or score >= NEAR_TAU:
        return info
    names = list(getattr(bank, "fact_entities", None) or [])
    if not any(entity_mentioned(name, query) for name in names):
        return info
    facts = info.get("facts") or []
    origin = next((item for item in facts if item.get("best")), None)
    if origin is None and facts:
        origin = facts[0]
    if not origin:
        return info
    rewrites = _rewrite_query(query, model, tok, device)
    if not rewrites:
        return info
    ensure_from = None
    try:
        from memory_core.paths import ensure_scripts_path

        ensure_scripts_path()
        from router import embed

        ensure_from = embed
    except Exception:
        return info
    vectors = ensure_from([query] + rewrites)
    for index, line in enumerate(rewrites, start=1):
        if float(vectors[0] @ vectors[index]) < 0.85:
            continue
        alt = bank.explain(line, tau)
        if not alt.get("matched"):
            continue
        if float(alt.get("best_question_sim") or 0.0) < NEAR_TAU:
            continue
        if str(alt.get("matched_attr") or "") != str(origin.get("attr") or ""):
            continue
        alt = dict(alt)
        alt["rescued_from"] = query
        facts = []
        for item in alt.get("facts") or []:
            row = dict(item)
            if row.get("passed") and str(row.get("attr") or "") == str(origin.get("attr") or ""):
                for key in ("fact_id", "node_id", "statement", "entity", "value", "question"):
                    if not row.get(key) and origin.get(key):
                        row[key] = origin.get(key)
            facts.append(row)
        alt["facts"] = facts
        return alt
    return info


# 问句相似度已经靠近某条事实、但属性短词还差一点时，用取值能不能回答来裁决。
# 0.575 卡在「车 / 汽车」属性分 0.543–0.562 和「单车」0.589 之间，不改事实闸的 τ。
CONSISTENCY_Q = 0.70
CONSISTENCY_ATTR = 0.575


def polar_question(query: str) -> str | None:
    """是非问句改成同属性的特指问句。改不成就返回 None，不拿「吗」去硬套。"""
    raw = (query or "").strip()
    if not raw or not has_cjk(raw):
        return None
    if not any(mark in raw for mark in ("是不是", "是否")):
        return None
    text = raw.rstrip("？?").strip()
    if "是不是叫" in text or "是否叫" in text:
        head = re.split(r"是不是叫|是否叫", text, maxsplit=1)[0].strip()
        return f"{head}叫什么？" if head else None
    head = re.split(r"是不是|是否", text, maxsplit=1)[0].strip()
    return f"{head}是什么？" if head else None


def polar_reply_from_fact(query: str, fact: dict[str, Any]) -> str | None:
    """是非问句已经对上某条事实时，用那条事实的取值回答，不再把原句丢给基座。"""
    if polar_question(query) is None:
        return None
    value = str(fact.get("value") or "").strip()
    if not value:
        return None
    if value in query:
        return f"是，{value}。"
    return f"不是，是{value}。"


def _parse_flag(text: str, key: str) -> bool | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    import json

                    data = json.loads(text[start : index + 1])
                except json.JSONDecodeError:
                    return None
                if not isinstance(data, dict) or key not in data:
                    return None
                value = data[key]
                if isinstance(value, bool):
                    return value
                return str(value).strip().casefold() in {"true", "yes", "1"}
    return None


def _value_answers(query: str, fact: dict[str, Any], model, tok, device) -> bool | None:
    """取值能不能回答这句问话。模型没给出 JSON 时返回 None，调用方不要据此放行。"""
    value = str(fact.get("value") or fact.get("answer") or "").strip()
    statement = str(fact.get("statement") or "").strip()
    if not value or not statement:
        return None
    english = not has_cjk(f"{query}{statement}{value}")
    if english:
        system = "You are a helpful assistant."
        prompt = (
            "A stored fact is given. Reply with JSON only.\n"
            '{"answers": true} if the value is a correct answer to the question.\n'
            '{"answers": false} if the question asks for a different object or a different attribute.\n'
            f"Fact: {statement}\nValue: {value}\nQuestion: {query}\n"
        )
    else:
        system = "你是助手。"
        prompt = (
            "下面有一条已经记住的事实。只输出 JSON。\n"
            "取值正好能回答这个问句时输出 {\"answers\": true}。\n"
            "问句在问别的事物或别的属性时输出 {\"answers\": false}。\n"
            f"事实：{statement}\n取值：{value}\n问句：{query}\n"
        )
    try:
        raw = _generate(model, tok, device, prompt, system)
    except Exception:
        return None
    return _parse_flag(raw, "answers")


def confirm_stored_answer(query: str, info: dict, model, tok, device) -> dict:
    """事实闸差一点没过、但取值确实能回答这句问话时，接受这条事实。

    不降低 τ。更笼统的「车 / 汽车」属性分停在这条线下面；咖啡、狗由模型否决。
    """
    from memory_core.fact_span import NEAR_TAU

    if info.get("matched") or model is None or tok is None or device is None:
        return info
    score = float(info.get("best_question_sim") or 0.0)
    if score < CONSISTENCY_Q or score >= NEAR_TAU:
        return info
    origin = next((item for item in info.get("facts") or [] if item.get("best")), None)
    if not origin:
        return info
    if float(origin.get("attr_sim") or 0.0) < CONSISTENCY_ATTR:
        return info
    if _value_answers(query, origin, model, tok, device) is not True:
        return info
    updated = dict(info)
    updated["matched"] = True
    updated["matched_attr"] = str(origin.get("attr") or "")
    updated["confirmed_answer"] = True
    facts = []
    for item in info.get("facts") or []:
        row = dict(item)
        row["passed"] = bool(item.get("best"))
        facts.append(row)
    updated["facts"] = facts
    return updated


class _nullctx:
    def __enter__(self):
        return None

    def __exit__(self, *args):
        return False

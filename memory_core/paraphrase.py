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
    if any(mark in question for mark in ("吗", "是不是", "是否", "对不对", "有没有")):
        return False
    if re.match(r"^(?:is|isn't|are|aren't|do|does|did|was|were|has|have)\b", question, re.IGNORECASE):
        return False
    return True


_EN_PROP = {
    "name", "color", "colour", "brand", "breed", "price",
    "job", "profession", "occupation", "instrument", "hometown", "age",
}
_EN_STOP = {
    "the", "a", "an", "of", "where", "they", "their", "what", "which", "who",
    "when", "how", "is", "are", "does", "do", "did", "was", "were", "and",
}


def _object_heads(attr: str) -> list[str]:
    """属性里的事物本身。颜色、名字、品牌是性质，不拿来当事物。"""
    attr = (attr or "").strip()
    if not attr:
        return []
    if has_cjk(attr):
        head = attr
        for suffix in ("的名字", "名字", "颜色", "品牌", "品种", "住址"):
            if head.endswith(suffix) and len(head) > len(suffix):
                head = head[: -len(suffix)]
                break
        head = head.strip("的")
        if "的" in head:
            head = head.split("的")[-1]
        return [head] if head else []
    if attr.casefold() == "where they live":
        return ["live"]
    words = re.findall(r"[A-Za-z0-9]+", attr.replace("'s", " ").replace("'", " "))
    heads = [word for word in words if word.casefold() not in _EN_PROP and word.casefold() not in _EN_STOP and word.casefold() != "s"]
    return heads[-1:] if heads else []


def _heads_in(text: str, heads: list[str]) -> bool:
    if not heads:
        return False
    if any(has_cjk(head) for head in heads):
        return all(head in text for head in heads)
    lowered = text.casefold()
    return all(re.search(r"\b" + re.escape(head) + r"\b", lowered) for head in heads)


def _query_properties(query: str) -> set[str]:
    if has_cjk(query):
        found = set()
        if any(mark in query for mark in ("颜色", "什么色", "啥色", "什么颜色")):
            found.add("颜色")
        if any(mark in query for mark in ("名字", "叫什么", "叫啥", "是叫", "是否叫", "是不是叫")):
            found.add("名字")
        if any(mark in query for mark in ("品牌", "牌子")):
            found.add("品牌")
        if "品种" in query:
            found.add("品种")
        if any(mark in query for mark in ("贵不贵", "多少钱", "价格", "贵吗")):
            found.add("价格")
        if "电动" in query:
            found.add("电动")
        if any(mark in query for mark in ("住哪", "住在", "住址", "住哪儿", "居住", "现居")):
            found.add("住址")
        if any(mark in query for mark in ("老家", "家乡", "长大", "籍贯")):
            found.add("家乡")
        if any(mark in query for mark in ("几岁", "多少岁", "年龄", "多大")):
            found.add("年龄")
        if "多高" in query or "身高" in query:
            found.add("身高")
        if any(mark in query for mark in ("电话", "手机", "邮箱", "邮件")):
            found.add("联系方式")
        if any(mark in query for mark in ("讨厌", "最恨")):
            found.add("讨厌")
        if any(mark in query for mark in ("职业", "工作", "谋生", "手艺")):
            found.add("职业")
        if any(mark in query for mark in ("乐器", "会弹", "弹什么")):
            found.add("乐器")
        return found
    lowered = query.casefold()
    found = set()
    if re.search(r"\bcolou?r\b", lowered):
        found.add("color")
    if re.search(r"\b(name|named|called)\b", lowered):
        found.add("name")
    if re.search(r"\bbrand\b", lowered):
        found.add("brand")
    if re.search(r"\bbreed\b", lowered):
        found.add("breed")
    if re.search(r"\b(price|expensive|cost)\b", lowered):
        found.add("price")
    if re.search(r"\belectric\b", lowered):
        found.add("electric")
    if re.search(r"\b(hometown|originally|grew up|grow up)\b", lowered):
        found.add("origin")
    elif "for a living" not in lowered and re.search(r"\b(live|lives|living|address)\b", lowered):
        found.add("residence")
    if re.search(r"\bhow old\b", lowered) or re.search(r"\bage\b", lowered):
        found.add("age")
    if re.search(r"\b(e-?mail|phone)\b", lowered):
        found.add("contact")
    if re.search(r"\b(hate|dislike|least favorite|least favourite)\b", lowered):
        found.add("dislike")
    if "for a living" in lowered or re.search(r"\b(job|profession|occupation)\b", lowered):
        found.add("occupation")
    if re.search(r"\b(instrument|play|plays)\b", lowered):
        found.add("instrument")
    return found


def _attr_properties(attr: str) -> set[str]:
    if has_cjk(attr):
        found = set()
        if "颜色" in attr or attr.endswith("色"):
            found.add("颜色")
        if "名字" in attr or attr.endswith("名"):
            found.add("名字")
        if "品牌" in attr or "牌子" in attr:
            found.add("品牌")
        if "品种" in attr:
            found.add("品种")
        if "住址" in attr or ("住" in attr and "家乡" not in attr):
            found.add("住址")
        if any(mark in attr for mark in ("老家", "家乡", "籍贯")):
            found.add("家乡")
        if any(mark in attr for mark in ("年龄", "岁")):
            found.add("年龄")
        if "身高" in attr:
            found.add("身高")
        if any(mark in attr for mark in ("电话", "手机", "邮箱")):
            found.add("联系方式")
        if "讨厌" in attr:
            found.add("讨厌")
        if "喜欢" in attr and "讨厌" not in attr:
            found.add("喜欢")
        if any(mark in attr for mark in ("职业", "工作")):
            found.add("职业")
        if "乐器" in attr:
            found.add("乐器")
        return found
    lowered = attr.casefold()
    found = set()
    if "color" in lowered or "colour" in lowered:
        found.add("color")
    if lowered.endswith("name") or " name" in lowered:
        found.add("name")
    if "brand" in lowered:
        found.add("brand")
    if "breed" in lowered:
        found.add("breed")
    if lowered == "where they live" or "live" in lowered:
        found.add("residence")
    if "hometown" in lowered or "origin" in lowered:
        found.add("origin")
    if "age" in lowered:
        found.add("age")
    if "email" in lowered or "phone" in lowered:
        found.add("contact")
    if "job" in lowered or "profession" in lowered or "occupation" in lowered:
        found.add("occupation")
    if "instrument" in lowered:
        found.add("instrument")
    if "hate" in lowered or "dislike" in lowered:
        found.add("dislike")
    return found


def property_conflict(query: str, attr: str) -> bool:
    """问句点名的性质和这条事实不是一回事，例如问品种、答名字。"""
    asked = _query_properties(query)
    have = _attr_properties(attr)
    if not asked:
        return False
    if asked & have:
        return bool(asked - have)
    return True


def _residence_paraphrase(query: str, attr: str) -> bool:
    if has_cjk(attr):
        if "住" not in attr and "址" not in attr:
            return False
        if "老家" in query or "家乡" in query:
            return False
        return any(mark in query for mark in ("住", "住址", "家在", "的家", "现居", "居住"))
    if attr.casefold() != "where they live":
        return False
    lowered = query.casefold()
    if "hometown" in lowered:
        return False
    return bool(re.search(r"\b(live|lives|living|home|address)\b", lowered))


def _without_entity(query: str, entity: str) -> str:
    if not entity:
        return query
    if has_cjk(entity):
        return query.replace(entity, "")
    text = re.sub(re.escape(entity), " ", query, flags=re.IGNORECASE)
    for part in entity.split():
        if len(part) > 2:
            text = re.sub(r"\b" + re.escape(part) + r"\b", " ", text, flags=re.IGNORECASE)
    return text


def _chunk_object(chunk: str) -> str:
    piece = re.split(r"什么|哪|吗|呢|是|叫|颜色|名字|品种|品牌|价格", chunk)[0].strip("的")
    if not piece or piece in {"那", "这", "一个", "一只", "那只", "那辆", "这个", "那辆车"}:
        return ""
    return piece


def _named_other_object(query: str, attr: str, entity: str = "") -> bool:
    """问句明确点了另一个事物。没写事物名不算点名。"""
    heads = _object_heads(attr)
    if not heads:
        return False
    bare = _without_entity(query, entity)
    if has_cjk(bare):
        for chunk in re.findall(r"的([\u4e00-\u9fff]{1,8})", bare):
            piece = _chunk_object(chunk)
            if piece and not any(head in piece for head in heads):
                return True
        return False
    for word in re.findall(r"'s\s+([A-Za-z]+)", query):
        token = word.casefold()
        if token in _EN_STOP or token in _EN_PROP or token == "s":
            continue
        if any(token == head.casefold() for head in heads):
            continue
        return True
    return False


def _foreign_object(query: str, attr: str, entity: str = "") -> bool:
    """问句里的事物和属性对不上，例如猫的名字问到了狗。"""
    heads = _object_heads(attr)
    if _heads_in(query, heads) or _residence_paraphrase(query, attr):
        return False
    if not heads:
        return False
    # 点了别的事物，或者根本没写出这条事实的事物名。后一种由 attribute_holds
    # 在问句和属性都够近时放行，例如「早上吃什么」对「早餐」。
    return True


def attribute_holds(query: str, info: dict) -> bool:
    """闸门选中的事实必须就是问句在问的那个属性。"""
    if not info.get("matched"):
        return True
    attr = str(info.get("matched_attr") or "")
    facts = [item for item in (info.get("facts") or []) if isinstance(item, dict)]
    best = next((item for item in facts if item.get("passed")), None)
    if best is None:
        best = next((item for item in facts if item.get("best")), None)
    entity = str((best or {}).get("entity") or "")
    if property_conflict(query, attr):
        return False
    # 问句已经和这条事实的某条问法几乎重合时，换个说法仍然是同一属性。
    # 0.91 下面的串属性（例如猫对上狗）到不了这条线。
    from memory_core.fact_span import NEAR_TAU

    best_sim = float((best or {}).get("question_sim") or info.get("best_question_sim") or 0.0)
    if best_sim >= NEAR_TAU:
        return True
    if _foreign_object(query, attr, entity):
        # 问句没点另一个事物，只是没用属性原词。调参分片上「早上吃什么」对「早餐」
        # 大约 0.85 / 0.69；点了猫、电话、老家的问句走上面的点名拦截，不走这里。
        attr_sim = float((best or {}).get("attr_sim") or 0.0)
        if (
            not _named_other_object(query, attr, entity)
            and best_sim >= SOFT_QUESTION
            and attr_sim >= SOFT_ATTR
        ):
            return True
        return False
    for item in facts:
        other = str(item.get("attr") or "")
        if not other or other == attr:
            continue
        other_heads = _object_heads(other)
        if _heads_in(query, other_heads) and not _heads_in(query, _object_heads(attr)):
            if not _residence_paraphrase(query, attr):
                return False
    return True


def _keeps_attribute(question: str, attr: str) -> bool:
    if property_conflict(question, attr):
        return False
    heads = _object_heads(attr)
    if heads and not _heads_in(question, heads) and not _residence_paraphrase(question, attr):
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


def structural_questions(fact: dict[str, Any]) -> list[str]:
    """用属性原词铺几种问法。模型没写出来时也有这些，而且不会把狗写成宠物、把颜色写成品牌。"""
    entity = str(fact.get("entity") or "").strip()
    attr = str(fact.get("attr") or "").strip()
    value = str(fact.get("value") or fact.get("answer") or "").strip()
    if not entity or not attr:
        return []
    found: list[str] = []

    def add(question: str) -> None:
        question = re.sub(r"\s+", " ", question).strip()
        if question and _usable(question, entity, value) and question not in found:
            found.append(question)

    if has_cjk(f"{entity}{attr}"):
        add(f"{entity}的{attr}是什么？")
        add(f"{entity}的{attr}是啥？")
        add(f"请问{entity}的{attr}是什么？")
        if attr.endswith("颜色"):
            head = attr[: -len("颜色")]
            add(f"{entity}的{head}是什么颜色？")
            add(f"{entity}{head}是什么颜色？")
            add(f"{entity}的{head}是什么色的？")
        if attr.endswith("的名字"):
            head = attr[: -len("的名字")]
            add(f"{entity}的{head}叫什么？")
            add(f"{entity}的{head}叫什么名字？")
            add(f"{entity}{head}的名字是什么？")
        if "住" in attr or attr == "住址":
            add(f"{entity}住在哪里？")
            add(f"{entity}住哪儿？")
            add(f"{entity}的住址在哪儿？")
            add(f"{entity}的住址是什么？")
        return found
    lowered = attr.casefold()
    if lowered != "where they live":
        add(f"What is {entity}'s {attr}?")
        add(f"What's {entity}'s {attr}?")
        add(f"What is the {attr} of {entity}?")
    if lowered.endswith(" color") or lowered.endswith(" colour"):
        head = attr.rsplit(" ", 1)[0]
        add(f"What color is {entity}'s {head}?")
        add(f"What colour is {entity}'s {head}?")
    if lowered.endswith("name"):
        head = re.sub(r"'s name$", "", attr, flags=re.IGNORECASE).strip()
        head = re.sub(r"\s+name$", "", head, flags=re.IGNORECASE).strip()
        add(f"What is the name of {entity}'s {head}?")
        add(f"What is {entity}'s {head} called?")
    if lowered == "where they live":
        add(f"Where does {entity} live?")
        add(f"Where is {entity}'s home?")
        add(f"What is {entity}'s address?")
    return found


def gate_questions_for_fact(fact: dict[str, Any], model, tok, device, limit: int = 8) -> list[str]:
    """先放下属性原词的问法，再收下模型改写里仍然问着同一属性的句子。"""
    entity = str(fact.get("entity") or "").strip()
    value = str(fact.get("value") or fact.get("answer") or "").strip()
    attr = str(fact.get("attr") or "").strip()
    if not entity:
        return []
    kept = structural_questions(fact)
    if len(kept) >= limit or model is None:
        return kept[:limit]
    existing = set(_source_questions(fact)) | set(kept)
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
            if attr and not _keeps_attribute(line, attr):
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
    structural = {question for fact in facts for question in structural_questions(fact)}
    grouped: dict[int, list[str]] = {index: [] for index in range(len(facts))}
    for row, (index, text) in enumerate(owned):
        scores = extra[row] @ base.T
        own = max((float(scores[col]) for col, owner in enumerate(base_owner) if owner == index), default=-1.0)
        other = max((float(scores[col]) for col, owner in enumerate(base_owner) if owner != index), default=-1.0)
        attr = str(facts[index].get("attr") or "")
        if attr and not _keeps_attribute(text, attr):
            continue
        if own + 1e-6 < other and not (text in structural and _residence_paraphrase(text, attr)):
            continue
        # 属性原词的问法只丢掉更像另一条事实的。模型改写还要过忠实检查，
        # 避免「pet's name」「哪个品牌」这种换了事物或性质的句子留下来。
        if text not in structural:
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


# 问句已经靠近某条事实时，再用取值能不能回答来确认。
# 具体数值在 persona_suite 的调参分片上选定。
CONSISTENCY_Q = 0.70
CONSISTENCY_ATTR = 0.64
# 没点名另一个事物时，问句和属性都要够近才算同一属性。线在调参分片上选定。
SOFT_QUESTION = 0.84
SOFT_ATTR = 0.65


def is_polar(query: str) -> bool:
    raw = (query or "").strip()
    if not raw:
        return False
    if has_cjk(raw):
        return any(mark in raw for mark in ("吗", "吧", "是不是", "是否", "有没有", "对不对", "贵不贵"))
    return bool(re.match(
        r"^(?:is|isn't|are|aren't|was|wasn't|does|doesn't|did|didn't|do|don't|has|hasn't|have|haven't)\b",
        raw.rstrip("?").strip(),
        re.IGNORECASE,
    ))


def _existence(query: str) -> bool:
    if "有没有" in query:
        return True
    return bool(re.match(r"^(?:do|does|did|has|have)\b", query.strip(), re.IGNORECASE)) and bool(
        re.search(r"\b(have|has|own|keep|got)\b", query, re.IGNORECASE)
    )


def polar_question(query: str) -> str | None:
    """是非问句改成同属性的特指问句。改写会换成别的性质时返回 None。"""
    raw = (query or "").strip()
    if not raw:
        return None
    text = raw.rstrip("？?").strip()
    if not has_cjk(raw):
        named = re.match(
            r"^(?:is|isn't|was|wasn't)\s+(?P<entity>.+?)'s\s+(?P<noun>.+?)\s+(?:named|called)\s+.+$",
            text,
            re.IGNORECASE,
        )
        if named:
            return f"What is {named.group('entity').strip()}'s {named.group('noun').strip()}'s name?"
        lives = re.match(
            r"^(?:does|doesn't|did|didn't)\s+(?P<entity>.+?)\s+live\s+in\s+.+$",
            text,
            re.IGNORECASE,
        )
        if lives:
            return f"Where does {lives.group('entity').strip()} live?"
        owns = re.match(
            r"^(?:do|does|did)\s+(?P<entity>.+?)\s+have\s+(?:a|an)\s+(?P<noun>[A-Za-z]+)",
            text,
            re.IGNORECASE,
        )
        if owns:
            return f"What is {owns.group('entity').strip()}'s {owns.group('noun').strip()}'s name?"
        generic = re.match(
            r"^(?:is|isn't|are|aren't|was|wasn't)\s+(?P<entity>.+?)'s\s+(?P<attr>.+?)\s+.+$",
            text,
            re.IGNORECASE,
        )
        if generic:
            return f"What is {generic.group('entity').strip()}'s {generic.group('attr').strip()}?"
        return None
    if any(mark in text for mark in ("贵不贵", "电动", "品种", "品牌", "牌子")):
        return None
    named_zh = re.match(
        r"^(?P<head>.+?)(?:是不是叫|是否叫|不是叫|是叫|叫)(?P<value>.+?)(?:吗|吧)?$",
        text,
    )
    if named_zh and "什么" not in named_zh.group("value") and "啥" not in named_zh.group("value"):
        return f"{named_zh.group('head')}叫什么？"
    if "是不是叫" in text or "是否叫" in text:
        head = re.split(r"是不是叫|是否叫", text, maxsplit=1)[0].strip()
        return f"{head}叫什么？" if head else None
    lives_zh = re.match(r"^(?P<head>.+?)(?:是不是|是否)住在", text)
    if lives_zh:
        return f"{lives_zh.group('head')}住在哪里？"
    owns = re.match(r"^(?P<entity>[^有]{1,16})有没有养?(?P<noun>[^？?]{1,8})$", text)
    if owns:
        return f"{owns.group('entity')}的{owns.group('noun')}叫什么？"
    if "是不是" in text or "是否" in text:
        head = re.split(r"是不是|是否", text, maxsplit=1)[0].strip()
        return f"{head}是什么？" if head else None
    return None


def guessed_value(query: str) -> str | None:
    text = (query or "").strip().rstrip("？?").strip()
    if not text:
        return None
    if has_cjk(text):
        patterns = (
            r"是不是叫(.+)$",
            r"是否叫(.+)$",
            r"不是叫(.+)$",
            r"是叫(.+?)(?:吗|吧)?$",
            r"(?<!什)叫(.+?)(?:吗|吧)$",
            r"是不是住在(.+)$",
            r"是否住在(.+)$",
            r"住在(.+?)(?:吗|吧)?$",
            r"弹(.+?)(?:吗|吧)?$",
            r"是不是(.+?)(?:吗|吧)?$",
            r"是否(.+)$",
            r"(?<!不)是(?!什么)(.+?)(?:吗|吧)$",
        )
        for pattern in patterns:
            matched = re.search(pattern, text)
            if not matched:
                continue
            value = matched.group(1).strip("的吗吧？? ")
            if value and value not in {"什么", "谁", "哪", "哪里", "哪儿", "啥"}:
                return value
        return None
    named = re.search(r"\b(?:named|called)\s+(.+)$", text, re.IGNORECASE)
    if named:
        return named.group(1).strip(" ?.!")
    lives = re.search(r"\blive in\s+(.+)$", text, re.IGNORECASE)
    if lives:
        return lives.group(1).strip(" ?.!")
    founded = re.search(r"\b(?:founded|established|started|born)\s+in\s+(.+)$", text, re.IGNORECASE)
    if founded:
        return founded.group(1).strip(" ?.!")
    based = re.search(r"\b(?:based|headquartered|located)\s+in\s+(.+)$", text, re.IGNORECASE)
    if based:
        return based.group(1).strip(" ?.!")
    generic = re.match(r"^(?:is|isn't|was|wasn't)\s+.+?'s\s+.+?\s+(.+)$", text, re.IGNORECASE)
    if generic:
        value = generic.group(1).strip(" ?.!")
        if value and value.casefold() not in {"what", "which", "who"}:
            return value
    return None


def _norm_value(text: str) -> str:
    return re.sub(r"[\s的。\.]", "", text or "").casefold()


def _same_value(left: str, right: str) -> bool:
    return bool(left) and _norm_value(left) == _norm_value(right)


def _values_agree(left: str, right: str) -> bool:
    """短的一边至少两个字，并且是另一边的子串。2011 对得上 2011年，墨绿色对得上墨绿色的。"""
    a = _norm_value(left)
    b = _norm_value(right)
    if not a or not b:
        return False
    if a == b:
        return True
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= 2 and short in long


def polar_reply_from_fact(query: str, fact: dict[str, Any]) -> str | None:
    """是非问句先回答是或否，再说出记住的取值。"""
    if not is_polar(query):
        return None
    value = str(fact.get("value") or "").strip()
    if not value:
        return None
    english = not has_cjk(query)
    if _existence(query):
        return f"Yes, {value}." if english else f"有，{value}。"
    proposed = guessed_value(query)
    if proposed and _values_agree(proposed, value):
        return f"Yes, {value}." if english else f"是，{value}。"
    if proposed:
        return f"No, {value}." if english else f"不是，是{value}。"
    if value.casefold() in query.casefold():
        return f"Yes, {value}." if english else f"是，{value}。"
    return None


def adjudicate(query: str, info: dict) -> dict:
    """问句和选中的事实不是同一属性时，撤回这次命中。"""
    if not info.get("matched") or attribute_holds(query, info):
        return info
    updated = dict(info)
    updated["matched"] = False
    updated["matched_attr"] = ""
    updated["confirmed_answer"] = False
    updated["polar_of"] = None
    updated["rejected_attribute"] = True
    facts = []
    for item in info.get("facts") or []:
        row = dict(item)
        row["passed"] = False
        facts.append(row)
    updated["facts"] = facts
    return updated


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
    if property_conflict(query, str(origin.get("attr") or "")):
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

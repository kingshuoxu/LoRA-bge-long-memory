"""实体级回答。

开放问句（介绍一下、相关信息、tell me about）不交给基座，列出该实体的全部已存事实。
问了已存实体但没写过的属性时，只说已经记住的，并说明其余的不在记忆里。
陈述句先自然确认，不把取值当成回答，也不假装已经训练过。
"""
from __future__ import annotations

import re
from typing import Any

from memory_core.fact_span import entity_mentioned
from memory_core.prompts import has_cjk

_OVERVIEW_TAILS = frozenset({
    "相关信息",
    "相关情况",
    "相关资料",
    "相关背景",
    "情况",
    "信息",
    "资料",
    "事情",
    "简介",
    "背景",
})

_DECOYS = ("1998", "圣迭戈", "圣地亚哥", "San Diego")

_ZH_PHRASES = (
    "其余的不在记忆里",
    "不在记忆里",
    "记住的是",
    "没有存过关于",
    "的具体事实",
    "的记忆",
    "关于",
)

_EN_WORDS = frozenset({
    "about", "what", "i", "have", "stored", "is", "the", "rest", "not", "in",
    "memory", "and", "a", "an", "of", "for", "this", "that", "dont", "don't",
    "anything", "are", "was", "were",
})

_REASON = {
    "entity_overview": "问句点了已存的实体，但没有问具体属性，所以列出这个实体的全部记忆",
    "entity_grounded": "问的是已存实体，这个属性没有记住，所以只回答已存事实",
    "statement_ack": "这句话是在陈述，先确认，还没有写入记忆",
}


def _compact(text: str) -> str:
    return re.sub(r"[\s?？!！。,，、]+", "", text or "")


def _overview_tail(chunk: str) -> bool:
    chunk = re.split(r"是|叫|吗|呢|吧|什么|哪|多少|几", chunk or "")[0]
    return chunk in _OVERVIEW_TAILS


def _de_topic(text: str, entity: str) -> str:
    if not text or not entity:
        return ""
    if has_cjk(text) or has_cjk(entity):
        matched = re.search(re.escape(entity) + r"的([\u4e00-\u9fff]{1,16})", text)
        if not matched:
            return ""
        chunk = matched.group(1)
        chunk = re.split(r"是|叫|吗|呢|吧|什么|哪|多少|几", chunk)[0]
        chunk = re.split(r"位于|在", chunk)[0]
        chunk = re.sub(r"不+$", "", chunk)
        return chunk.strip("的")
    matched = re.search(
        re.escape(entity) + r"(?:'s|’s|'|’)\s+([A-Za-z][\w' -]{0,48})",
        text,
        re.IGNORECASE,
    )
    if not matched:
        return ""
    rest = matched.group(1)
    rest = re.split(r"\b(?:is|are|was|were|named|called)\b", rest, maxsplit=1, flags=re.IGNORECASE)[0]
    rest = re.sub(r"^(?:the|a|an)\s+", "", rest.strip(), flags=re.IGNORECASE)
    return rest.strip(" ?.!")


def _specific_attribute(text: str, entity: str) -> bool:
    topic = _de_topic(text, entity)
    return bool(topic) and not _overview_tail(topic)


def open_entity_question(text: str, entity: str) -> bool:
    """点了实体、但没有问具体属性的介绍类问句。"""
    if not entity or not entity_mentioned(entity, text):
        return False
    if _specific_attribute(text, entity):
        return False
    if has_cjk(text) or has_cjk(entity):
        compact = _compact(text)
        cues = (
            f"介绍一下{entity}",
            f"介绍下{entity}",
            f"介绍{entity}",
            f"说说{entity}",
            f"讲讲{entity}",
            f"聊聊{entity}",
            f"告诉我{entity}",
            f"告诉我关于{entity}",
            f"关于{entity}",
            f"{entity}相关信息",
            f"{entity}相关情况",
            f"{entity}相关资料",
            f"{entity}的情况",
            f"{entity}的信息",
            f"{entity}的资料",
            f"{entity}的事情",
            f"{entity}的简介",
            f"{entity}的背景",
            f"{entity}的相关信息",
            f"{entity}的相关情况",
        )
        return any(cue in compact for cue in cues)
    compact = re.sub(r"\s+", " ", text).strip()
    name = re.escape(entity)
    patterns = (
        rf"\btell me about {name}\b",
        rf"\btell me everything about {name}\b",
        rf"\beverything about {name}\b",
        rf"\ball about {name}\b",
        rf"\bwhat do you know about {name}\b",
        rf"\bwhat can you tell me about {name}\b",
        rf"\bwhat about {name}\b",
        rf"\boverview of {name}\b",
        rf"\bsummar(?:y|ize)(?: of)? {name}\b",
        rf"\bdescribe {name}\b",
        rf"\bwho is {name}\b",
        rf"\bwhat is {name}\b",
    )
    return any(re.search(pattern, compact, re.IGNORECASE) for pattern in patterns)


def _extra_property(text: str) -> str:
    if has_cjk(text):
        if "品种" in text:
            return "品种"
        if "贵" in text:
            return "价格"
        if "电动" in text:
            return "是否电动"
        if any(mark in text for mark in ("多大", "几岁", "多少岁", "年龄")):
            return "年龄"
        if "多高" in text or "身高" in text:
            return "身高"
        if "妹妹" in text:
            return "妹妹的名字"
        if "电话" in text or "手机" in text:
            return "电话"
        if "邮箱" in text or "邮件" in text:
            return "邮箱"
        return ""
    lowered = text.casefold()
    if "breed" in lowered:
        return "breed"
    if "expensive" in lowered or re.search(r"\bprice\b", lowered):
        return "price"
    if "electric" in lowered:
        return "whether it is electric"
    if re.search(r"\bhow old\b", lowered) or re.search(r"\bage\b", lowered):
        return "age"
    if re.search(r"\bhow tall\b", lowered) or re.search(r"\bheight\b", lowered):
        return "height"
    if "sister" in lowered:
        return "sister's name"
    if "phone" in lowered:
        return "phone number"
    if re.search(r"\be-?mail\b", lowered):
        return "email address"
    return ""


def _object_known(topic: str, facts: list[dict]) -> bool:
    if not topic:
        return False
    if has_cjk(topic):
        head = topic.split("的")[0]
        return any(head and (head in str(fact.get("attr") or "")) for fact in facts)
    head = topic.split()[0].casefold().strip("'s") if topic.split() else ""
    return any(head and head in str(fact.get("attr") or "").casefold() for fact in facts)


def missing_topic(text: str, entity: str, facts: list[dict]) -> str:
    """问句点名、但记忆里没有的那个属性。已知事物不再说成完全没有。"""
    extra = _extra_property(text)
    if extra:
        return extra
    topic = _de_topic(text, entity)
    if not topic or _overview_tail(topic):
        return ""
    if _object_known(topic, facts):
        return ""
    return topic


def _personal_marks(text: str, entity: str) -> bool:
    if not entity_mentioned(entity, text):
        return False
    if has_cjk(text):
        return any(mark in text for mark in ("的", "住", "叫", "养", "吗"))
    if re.search(re.escape(entity) + r"(?:'s|’s)", text, re.IGNORECASE):
        return True
    return bool(re.search(r"\b(name|named|called|live|lives|colour|color)\b", text, re.IGNORECASE))


def concerns_entity(text: str, entity: str, facts: list[dict]) -> bool:
    if not entity_mentioned(entity, text):
        return False
    if open_entity_question(text, entity):
        return True
    if missing_topic(text, entity, facts):
        return True
    topic = _de_topic(text, entity)
    if topic and not _overview_tail(topic):
        return True
    return _personal_marks(text, entity)


def _english_facts(entity: str, facts: list[dict]) -> bool:
    if has_cjk(entity):
        return False
    blob = entity + "".join(str(fact.get("attr") or "") + str(fact.get("value") or "") for fact in facts)
    return not has_cjk(blob)


def _label(entity: str, english: bool) -> str:
    if entity == "我":
        return "you" if english else "你"
    if english and entity.casefold() in {"i", "me"}:
        return "you"
    return entity


def overview_reply(entity: str, facts: list[dict], missing: str = "") -> str:
    """只使用已存取值。没有的部分明说不在记忆里。"""
    usable = [fact for fact in facts if str(fact.get("value") or fact.get("answer") or "").strip()]
    english = _english_facts(entity, usable)
    label = _label(entity, english)
    if not usable:
        if english:
            return f"I don't have anything stored about {label}."
        return f"没有存过关于{label}的记忆。"
    pieces = []
    for fact in usable:
        attr = str(fact.get("attr") or "").strip()
        value = str(fact.get("value") or fact.get("answer") or "").strip()
        if english:
            pieces.append(f"{attr} is {value}" if attr else value)
        else:
            pieces.append(f"{attr}是{value}" if attr else value)
    if english:
        head = f"About {label}, what I have stored is: {'; '.join(pieces)}."
        if missing:
            return f"{head} {missing} is not in memory."
        return f"{head} The rest is not in memory."
    head = f"关于{label}，记住的是：{'；'.join(pieces)}。"
    if missing:
        return f"{head}{missing}不在记忆里。"
    return f"{head}其余的不在记忆里。"


def _topic_piece(text: str, entity: str) -> str:
    extra = _extra_property(text)
    if extra:
        return extra
    topic = _de_topic(text, entity)
    if topic and not _overview_tail(topic):
        return topic
    rest = text
    if entity:
        rest = rest.replace(entity, "")
    if has_cjk(text):
        rest = re.sub(r"[的是叫吗呢吧什么哪谁多少几？?，。]", "", rest)
        rest = re.split(r"位于|在", rest)[0]
        rest = re.sub(r"不+$", "", rest).strip()
        return rest[:12]
    rest = re.sub(r"\b(what|where|who|which|when|how|is|are|was|were|does|do|did|the|a|an|of|about)\b", " ", rest, flags=re.IGNORECASE)
    rest = re.sub(r"[^A-Za-z0-9' -]", " ", rest)
    rest = re.sub(r"\s+", " ", rest).strip(" '\"")
    return rest[:48]


def abstain_reply(entity: str, text: str) -> str:
    """没记住的属性只说不在记忆里，不把别的取值写进回答。"""
    topic = _topic_piece(text, entity)
    english = not has_cjk(text)
    label = _label(entity, english)
    if english:
        if topic:
            return f"{topic} is not in memory."
        return f"I don't have that stored about {label}."
    if topic:
        return f"{topic}不在记忆里。"
    return f"没有存过关于{label}的这件事。"


def acknowledge_statement(fact: dict[str, Any]) -> str:
    """陈述句的确认。不复读成孤零零的取值，也不说已经训练好。"""
    entity = str(fact.get("entity") or "").strip()
    attr = str(fact.get("attr") or "").strip().replace("的的", "的")
    value = str(fact.get("value") or "").strip()
    if has_cjk(f"{entity}{attr}{value}"):
        who = "你" if entity == "我" else entity
        if attr.endswith("的名字"):
            head = attr[: -len("的名字")]
            return f"好，{who}的{head}叫{value}。"
        if "住" in attr and "家乡" not in attr:
            return f"好，{who}住在{value}。"
        if attr.startswith(("最", "比较", "非常")):
            return f"好，{who}{attr}是{value}。"
        return f"好，{who}的{attr}是{value}。"
    if entity.casefold() in {"i", "me"}:
        return f"Got it, your {attr} is {value}."
    return f"Got it, {entity}'s {attr} is {value}."


def known_entity_names(content: str, experts: list[Any]) -> list[str]:
    found: list[str] = []
    for expert in experts:
        memory = getattr(expert, "fact_memory", None) or {}
        facts = memory.get("facts") if isinstance(memory, dict) else None
        names = [str(fact.get("entity") or "") for fact in facts or [] if isinstance(fact, dict)]
        names.extend(str(name) for name in (getattr(expert, "entities", None) or []))
        for name in names:
            if name and entity_mentioned(name, content) and name not in found:
                found.append(name)
    return found


def _active_facts(expert: Any, entity: str) -> list[dict]:
    memory = getattr(expert, "fact_memory", None) or {}
    rows = []
    for fact in memory.get("facts") or []:
        if not isinstance(fact, dict) or fact.get("superseded"):
            continue
        if str(fact.get("entity") or "") == entity:
            rows.append(fact)
        elif not has_cjk(entity) and str(fact.get("entity") or "").casefold() == entity.casefold():
            rows.append(fact)
    return rows


def gather_facts(experts: list[Any], entity: str) -> tuple[Any, list[dict]]:
    owner = None
    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    best_n = -1
    for expert in experts:
        local = _active_facts(expert, entity)
        if not local and entity not in (getattr(expert, "entities", None) or []):
            continue
        fresh = []
        for fact in local:
            key = (str(fact.get("attr") or ""), str(fact.get("value") or fact.get("answer") or ""))
            if key in seen:
                continue
            seen.add(key)
            fresh.append(fact)
        if owner is None or len(fresh) > best_n:
            owner = expert
            best_n = len(fresh)
        rows.extend(fresh)
    return owner, rows


def overview_if_open(content: str, experts: list[Any]) -> tuple[str, Any, list[dict]] | None:
    names = sorted(known_entity_names(content, experts), key=len, reverse=True)
    for name in names:
        if not open_entity_question(content, name):
            continue
        expert, facts = gather_facts(experts, name)
        if expert is None:
            continue
        return overview_reply(name, facts), expert, facts
    return None


def ground_if_unknown(
    content: str,
    experts: list[Any],
    *,
    rejected: bool = False,
    routed_expert: str | None = None,
) -> tuple[str, Any, list[dict]] | None:
    names = sorted(known_entity_names(content, experts), key=len, reverse=True)
    if rejected and routed_expert:
        expert = next((item for item in experts if getattr(item, "name", None) == routed_expert), None)
        mentioned = [name for name in names if expert is not None and (_active_facts(expert, name) or name in (expert.entities or []))]
        if expert is not None and mentioned:
            name = mentioned[0]
            facts = _active_facts(expert, name)
            return abstain_reply(name, content), expert, facts
    for name in names:
        expert, facts = gather_facts(experts, name)
        if expert is None:
            continue
        if not concerns_entity(content, name, facts):
            continue
        return abstain_reply(name, content), expert, facts
    return None


def _short_object(query: str, heads: list[str]) -> bool:
    """问句里的事物只比事实里的事物名少一个字，并且是它的后缀。

    车对得上汽车。自行车比车多两个字，单车也不是自行车的后缀，这两对都不算同一个事物。
    """
    if not any(has_cjk(head) for head in heads):
        return False
    from memory_core.paraphrase import _chunk_object

    for chunk in re.findall(r"的([\u4e00-\u9fff]{1,8})", query):
        piece = _chunk_object(chunk)
        if not piece:
            continue
        if any(has_cjk(head) and len(head) == len(piece) + 1 and head.endswith(piece) for head in heads):
            return True
    return False


def _answer_attr(fact: dict) -> str:
    """问句对的是性质，旧事实可能只写下了事物名。

    「汽车 / 珍珠白的」仍是颜色，「鹦鹉 / 叫小翠」仍是名字。
    只看取值和原句的形态，不把某个词写死成属性。
    """
    from memory_core.extract import _EN_COLOR, _ZH_COLOR

    attr = str(fact.get("attr") or "").strip()
    value = str(fact.get("value") or fact.get("answer") or "").strip()
    statement = str(fact.get("statement") or "")
    if has_cjk(f"{attr}{value}{statement}"):
        if "名" not in attr and value and re.search(r"叫" + re.escape(value), statement):
            attr = f"{attr}的名字" if attr else "名字"
        elif "名" not in attr and "色" not in attr and value and _ZH_COLOR.match(value):
            attr = f"{attr}颜色" if attr else "颜色"
        return attr
    lowered = attr.casefold()
    if value and _EN_COLOR.match(value) and "color" not in lowered and "colour" not in lowered:
        attr = f"{attr} color" if attr else "color"
    return attr


def _pick_fact(query: str, facts: list[dict]) -> dict | None:
    from memory_core.paraphrase import _heads_in, _named_other_object, _object_heads, property_conflict
    from memory_core.relations import fact_relations, query_relations

    asked = query_relations(query)
    ranked: list[tuple[int, dict]] = []
    for fact in facts:
        attr = _answer_attr(fact)
        statement = str(fact.get("statement") or "")
        have = fact_relations(attr, statement)
        if asked and not (asked & have):
            continue
        if property_conflict(query, attr):
            continue
        heads = _object_heads(attr)
        entity = str(fact.get("entity") or "")
        short = bool(heads and _short_object(query, heads))
        if heads and not _heads_in(query, heads) and not short:
            # 会弹古筝并不写出「乐器」，但仍是同一关系，可以和已存的乐器取值比较。
            loose = asked & {
                "residence",
                "origin",
                "occupation",
                "founding",
                "headquarters",
                "founder",
                "headcount",
                "instrument",
            }
            if _named_other_object(query, attr, entity) or not loose:
                continue
        score = len(asked & have)
        if "founder" in (asked & have) and any(mark in query for mark in ("谁", "who", "Whom")):
            score += 3
        if "name" in (asked & have):
            score += 1
        if not asked and heads and (_heads_in(query, heads) or short):
            score += 1
        ranked.append((score, fact))
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0], reverse=True)
    if not asked and ranked[0][0] <= 0:
        return None
    return ranked[0][1]


def _legacy_expert(expert: Any) -> bool:
    memory = getattr(expert, "fact_memory", None) or {}
    if isinstance(memory, dict) and memory.get("legacy"):
        return True
    return not getattr(expert, "explicit", True)


def _legacy_reply(entity: str, text: str) -> str:
    english = not has_cjk(text)
    if english:
        return (
            f"{entity} is an older expert saved on disk. "
            "This question does not line up with the stored facts. "
            "Please consolidate it again. The base model will not fill it in."
        )
    return f"「{entity}」是旧版本留下的专家，这条问法对不上已保存的事实。请重新巩固，基座不会替它编。"


def _clarify_reply(stored: str, span: str, text: str) -> str:
    english = not has_cjk(text)
    if english:
        return f"I have {stored} stored, not {span}."
    return f"记忆里有「{stored}」，没有「{span}」。"


def resolve_stored_reply(
    content: str,
    experts: list[Any],
    mentions: list[str] | None = None,
) -> tuple[str, Any, list[dict], str] | None:
    """已知实体或只被提到过的实体，只从记忆回答，不交给基座。

    开放问句列出已存事实。具体问句只给对上的取值，或一句不借用其他取值的拒答。
    问句没有点到这类实体时返回 None，调用方再决定要不要用基座。
    """
    from memory_core.correct import utterance_is_question
    from memory_core.paraphrase import is_polar, polar_reply_from_fact

    from memory_core.fact_span import near_miss_span

    mentions = list(mentions or [])
    names = sorted(known_entity_names(content, experts), key=len, reverse=True)
    if not names:
        for expert in experts:
            stored = list(getattr(expert, "entities", None) or [])
            memory = getattr(expert, "fact_memory", None) or {}
            if isinstance(memory, dict):
                stored.extend(str(fact.get("entity") or "") for fact in memory.get("facts") or [] if isinstance(fact, dict))
            for name in stored:
                span = near_miss_span(name, content)
                if span:
                    return _clarify_reply(name, span, content), None, [], "entity_clarify"
    hinted = []
    for name in sorted(mentions, key=len, reverse=True):
        if name and name not in names and entity_mentioned(name, content):
            hinted.append(name)
    if not names and not hinted:
        return None
    if not utterance_is_question(content) and not any(open_entity_question(content, name) for name in names + hinted):
        return None
    if not names:
        return abstain_reply(hinted[0], content), None, [], "entity_grounded"
    name = names[0]
    expert, facts = gather_facts(experts, name)
    if expert is None:
        return abstain_reply(name, content), None, [], "entity_grounded"
    if open_entity_question(content, name):
        if facts or not _legacy_expert(expert):
            return overview_reply(name, facts), expert, facts, "entity_overview"
        return _legacy_reply(name, content), expert, [], "legacy_retrain"
    fact = _pick_fact(content, facts)
    if is_polar(content):
        if fact is None:
            return _unmatched(name, content, expert)
        reply = polar_reply_from_fact(content, fact)
        if not reply:
            return _unmatched(name, content, expert)
        return reply, expert, [fact], "entity_first"
    if fact is not None:
        value = str(fact.get("value") or fact.get("answer") or "").strip()
        if value:
            return value, expert, [fact], "entity_first"
    return _unmatched(name, content, expert)


def _unmatched(name: str, content: str, expert: Any) -> tuple[str, Any, list[dict], str]:
    """旧专家对不上时说明要重新巩固。新专家仍只说这个属性不在记忆里。"""
    if expert is not None and _legacy_expert(expert):
        return _legacy_reply(name, content), expert, [], "legacy_retrain"
    return abstain_reply(name, content), expert, [], "entity_grounded"


def matched_rows(facts: list[dict]) -> list[dict]:
    rows = []
    for fact in facts:
        fact_id = str(fact.get("id") or "")
        rows.append({
            "fact_id": fact_id,
            "node_id": f"fact:{fact_id}" if fact_id else "",
            "statement": fact.get("statement") or "",
            "entity": fact.get("entity") or "",
            "attr": fact.get("attr") or "",
            "value": fact.get("value") or fact.get("answer") or "",
            "passed": True,
            "grounded": True,
        })
    return rows


def mount_memory(decision: Any, recall: dict, expert: Any, facts: list[dict], reason: str) -> None:
    label = f"记忆 · {getattr(expert, 'display_name', None) or expert.name}"
    decision.fired = True
    decision.expert = expert.name
    decision.label = label
    decision.reason = reason
    decision.entity_pass = True
    decision.fact_pass = True
    recall["fired"] = True
    recall["abstain"] = False
    recall["mounted"] = True
    recall["reason"] = reason
    recall["reason_text"] = _REASON.get(reason, reason)
    recall["expert"] = expert.name
    recall["mounted_expert"] = expert.name
    recall["mounted_label"] = label
    recall["matched_facts"] = matched_rows(facts)
    recall["wording"] = "这些是这个实体已经记下的事实。没问到的部分不在记忆里，基座没有补写。"
    for row in recall.get("experts") or []:
        chosen = row.get("name") == expert.name
        row["chosen"] = chosen
        if chosen:
            row["considered"] = True
    gate = dict(recall.get("fact_gate") or {})
    gate["grounded"] = True
    gate["matched"] = True
    recall["fact_gate"] = gate


def statement_trace() -> dict:
    return {
        "fired": False,
        "abstain": True,
        "mounted": False,
        "reason": "statement_ack",
        "reason_text": _REASON["statement_ack"],
        "expert": None,
        "mounted_expert": None,
        "mounted_label": "基座",
        "sim": 0.0,
        "thresholds": {},
        "experts": [],
        "fact_gate": None,
        "matched_facts": [],
        "wording": "陈述还没有写入记忆。",
    }


def contradicting_facts(reply: str, facts: list[dict], topic: str = "") -> list[str]:
    """回复里不属于已存事实、也不属于固定说法的声称。"""
    stored = " ".join(str(fact.get("value") or "") for fact in facts).casefold()
    found = [decoy for decoy in _DECOYS if decoy.casefold() in reply.casefold() and decoy.casefold() not in stored]
    found.extend(_leftover_claims(reply, facts, topic))
    return found


def _cut_piece(text: str, piece: str) -> str:
    """拉丁取值按词切，避免 red 把 stored 切成 sto。"""
    if has_cjk(piece):
        return text.replace(piece, " ")
    pattern = re.compile(r"(?<![A-Za-z])" + re.escape(piece) + r"(?![A-Za-z])", re.IGNORECASE)
    return pattern.sub(" ", text)


def _leftover_claims(reply: str, facts: list[dict], topic: str) -> list[str]:
    scrubbed = reply
    pieces = [topic] if topic else []
    for fact in facts:
        pieces.extend([
            str(fact.get("statement") or ""),
            str(fact.get("entity") or ""),
            str(fact.get("attr") or ""),
            str(fact.get("value") or ""),
            str(fact.get("answer") or ""),
        ])
    for piece in sorted({item for item in pieces if item}, key=len, reverse=True):
        scrubbed = _cut_piece(scrubbed, piece)
    for phrase in _ZH_PHRASES:
        scrubbed = scrubbed.replace(phrase, " ")
    tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z'-]{2,}|\d{2,}", scrubbed)
    return [token for token in tokens if token.casefold() not in _EN_WORDS]

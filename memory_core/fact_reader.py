"""跨全部专家用 bge 找回事实，再让基座只从这些句子里摘答案。

不按专家名路由。先取和问句最像的几句，再补上一跳：和它们共用实体或取值的句子。
基座只能抄原文里的一段，或者写 NONE。抄出来的字必须真的在某一句里，
并且不能只是问句里已经点到的那个主体。对不上就说明不在记忆里。
"""
from __future__ import annotations

import re
from typing import Any, Callable

from memory_core.fact_recall import (
    _cosine,
    answer_span,
    possessed_name_query,
    strong_value_spans,
    touches_memory,
)
from memory_core.prompts import has_cjk

TOP_K = 3
POOL_LIMIT = 6
# 常识题和灯塔事实的相似度落在 0.30 以下，改写题在 0.44 以上。
MEMORY_SIM = 0.38

_READER = (
    "你是摘录员。只能从给出的句子里原样抄几个字当答案。"
    "问的事物必须和句子说的是同一个。句子里没有就只写 NONE。不要解释。"
)
_MUST_MENTION = (
    "生日", "妻子", "丈夫", "市长", "母亲", "父亲", "电话", "学校",
    "老婆", "老公", "多远", "几岁", "年龄", "公司", "上班",
)
_KIN = (
    frozenset({"女儿", "闺女", "丫头"}),
    frozenset({"儿子", "小子"}),
    frozenset({"妻子", "老婆", "夫人", "太太"}),
    frozenset({"丈夫", "老公"}),
    frozenset({"海鸥", "鸟", "鸟儿", "海鸟"}),
    frozenset({"猫", "猫咪", "宠物猫"}),
    frozenset({"灯塔", "塔"}),
    frozenset({"海盐", "盐"}),
)


def _statement(fact: dict) -> str:
    return str(fact.get("statement") or fact.get("value") or "").strip()


def _compact(text: str) -> str:
    return re.sub(r"[\s，,。.!！？?、；;：:「」\"'（）()]", "", text or "")


def _same_kind(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    return any(left in group and right in group for group in _KIN)


def _possession_heads(fact: dict) -> list[str]:
    statement = _statement(fact)
    attr = str(fact.get("attr") or "")
    heads = []
    for match in re.finditer(r"的([\u4e00-\u9fff]{1,6}?)(?:颜色|的名字|名字是)", statement + attr):
        head = match.group(1)
        if head and head not in heads:
            heads.append(head)
    return heads


def _asked_heads(query: str) -> list[str]:
    found = []
    for match in re.finditer(r"的([\u4e00-\u9fff]{1,8}?)(?:颜色|名字|叫|是什么)", query or ""):
        head = _normalize_head(re.split(r"的|是", match.group(1))[-1])
        if head and head not in found:
            found.append(head)
    for word in ("汽车", "自行车", "猫咪", "宠物猫", "古筝"):
        if word in (query or "") and word not in found:
            found.append(word)
    if "狗" in (query or "") and "狗" not in found:
        found.append("狗")
    if re.search(r"(?<![自火汽])车", query or "") and "汽车" not in (query or "") and "自行车" not in (query or ""):
        found.append("车")
    return found


def clashes(query: str, fact: dict) -> bool:
    """问的是另一个东西，例如汽车对自行车、狗对猫。闺女和鸟这种说法不算冲突。"""
    owned = possessed_name_query(query)
    statement = _statement(fact)
    if owned and owned not in statement and not any(_same_kind(owned, piece) for piece in re.findall(r"[\u4e00-\u9fff]{1,4}", statement)):
        return True
    heads = _possession_heads(fact)
    asked = _asked_heads(query)
    if not heads or not asked:
        return False
    for head_q in asked:
        if any(_same_kind(head_q, head) for head in heads):
            return False
        if any(head_q == head for head in heads):
            return False
    return True


def _link_tokens(fact: dict) -> set[str]:
    statement = _statement(fact)
    tokens = set(strong_value_spans(statement))
    entity = str(fact.get("entity") or "").strip()
    if len(entity) >= 2:
        tokens.add(entity)
    value = str(fact.get("value") or "").strip().rstrip("。")
    if 2 <= len(value) <= 12:
        tokens.add(value)
    for match in re.finditer(r"名叫([\u4e00-\u9fffA-Za-z0-9·]{1,12})", statement):
        tokens.add(match.group(1))
    for match in re.finditer(r"([\u4e00-\u9fff]{2,3})养了", statement):
        tokens.add(match.group(1))
    return {token for token in tokens if len(token) >= 2}


def shares_hop(left: dict, right: dict) -> bool:
    if left is right:
        return False
    shared = _link_tokens(left) & _link_tokens(right)
    if shared:
        return True
    for fact, other in ((left, right), (right, left)):
        entity = str(fact.get("entity") or "").strip()
        if len(entity) >= 2 and entity in _statement(other):
            return True
    return False


def _score_facts(query: str, facts: list[dict], query_vector: list[float] | None, fact_vectors: list[list[float]] | None) -> list[tuple[float, dict]]:
    ranked = []
    for index, fact in enumerate(facts):
        if not isinstance(fact, dict) or fact.get("superseded") or not _statement(fact):
            continue
        if query_vector is not None and fact_vectors is not None and index < len(fact_vectors):
            score = _cosine(query_vector, fact_vectors[index])
        else:
            score = 0.0
        ranked.append((score, fact))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked


def retrieve(query: str, facts: list[dict], query_vector: list[float] | None = None, fact_vectors: list[list[float]] | None = None) -> tuple[list[dict], float]:
    """按问句相似度取前几句，再补上和它们共用实体或取值的一跳。"""
    ranked = _score_facts(query, facts, query_vector, fact_vectors)
    if not ranked:
        return [], 0.0
    best = ranked[0][0]
    seeds = [fact for score, fact in ranked[:TOP_K] if score >= MEMORY_SIM or (query_vector is None and score == 0.0)]
    if query_vector is None:
        seeds = [fact for _score, fact in ranked[:TOP_K]]
    pool: list[dict] = []
    for fact in seeds:
        if fact not in pool:
            pool.append(fact)
    for fact in list(pool):
        for _score, other in ranked:
            if other in pool or not shares_hop(fact, other):
                continue
            pool.append(other)
            if len(pool) >= POOL_LIMIT:
                break
        if len(pool) >= POOL_LIMIT:
            break
    return pool[:POOL_LIMIT], best


def _overlaps(query: str, fact: dict) -> bool:
    """问句和这句除了人名以外还有没有共同的事物。常识题因此不会被算成记忆题。"""
    statement = _statement(fact)
    entity = str(fact.get("entity") or "")
    for token in _link_tokens(fact):
        if len(token) >= 2 and token != entity and token in query:
            return True
    for group in _KIN:
        if any(word in query for word in group) and any(word in statement for word in group):
            return True
    for word in ("颜色", "住址", "地址", "茶", "灯塔", "海盐", "透镜", "电灯", "晒", "晾"):
        if word in query and word in statement:
            return True
    if any(mark in query for mark in ("住哪", "住在", "住哪儿", "居住")) and "住" in statement:
        return True
    return False


def memory_question(query: str, facts: list[dict], best_sim: float, pool: list[dict] | None = None) -> bool:
    if touches_memory(query, facts):
        return True
    if best_sim < MEMORY_SIM:
        return False
    return any(_overlaps(query, fact) for fact in (pool or facts[:TOP_K]))


def _normalize_head(head: str) -> str:
    text = re.sub(r"^(?:那|这|一)?(?:只|座|辆|个)", "", head or "")
    text = re.sub(r"(?:名字|名)$", "", text)
    return text


def _focus(query: str) -> str:
    match = re.search(
        r"([\u4e00-\u9fff]{1,8})(?:叫什么|有多高|多少|哪一年|哪年|什么时候|是谁|几面|多远)",
        query or "",
    )
    if not match:
        return ""
    return _normalize_head(match.group(1).split("的")[-1])


def _hosts(query: str, pool: list[dict]) -> list[dict]:
    usable = [fact for fact in pool if not clashes(query, fact) and not off_topic(query, fact)]
    focus = _focus(query)
    if focus and any(focus in _statement(fact) for fact in usable):
        focused = [fact for fact in usable if focus in _statement(fact)]
        if focused:
            return focused
    return usable


def _asked_relation(query: str) -> str:
    """紧挨着疑问词的那个关系，不管前面用来指路的字。"""
    match = re.search(r"的([\u4e00-\u9fff]{1,6})(?:叫什么|是谁|是什么|有多|在哪|哪年|什么时候)", query or "")
    if not match:
        return ""
    return _normalize_head(re.split(r"的|是", match.group(1))[-1])


def _head_in_statement(head: str, statement: str) -> bool:
    if head and head in statement:
        return True
    for group in _KIN:
        if head in group and any(piece in statement for piece in group):
            return True
    return False


def off_topic(query: str, fact: dict) -> bool:
    """问句点了另一个事物，而这句里没有它，也没有它的通俗说法。"""
    statement = _statement(fact)
    if "吃" in query and "吃" not in statement:
        return True
    if "弹" in query and "弹" not in statement:
        return True
    heads = _asked_heads(query)
    if not heads:
        return False
    return not any(_head_in_statement(head, statement) for head in heads)


def unsupported(query: str, pool: list[dict]) -> str:
    """问句真正要的那个关系，几句里都没写。"""
    blob = "\n".join(_statement(fact) for fact in pool)
    relation = _asked_relation(query)
    if relation in _MUST_MENTION and relation not in blob and not _head_in_statement(relation, blob):
        return relation
    for mark in ("市长", "妻子", "丈夫", "母亲", "电话", "学校", "老婆", "老公"):
        if mark in query and mark not in blob:
            return mark
    if any(mark in query for mark in ("几岁", "多大", "今年几")) and not re.search(r"岁|年龄", blob):
        return "几岁"
    if "多远" in query and not re.search(r"远|公里", blob):
        return "多远"
    if "生日" in query and "生日" not in blob:
        return "生日"
    if any(mark in query for mark in ("多少钱", "价格", "几斤")) and not any(mark in blob for mark in ("钱", "价格", "斤")):
        return "多少钱"
    return ""


def _echo(span: str, query: str) -> bool:
    text = _compact(span).rstrip("。")
    if len(text) < 2:
        return False
    return text in _compact(query)


def _literal(span: str, statement: str) -> bool:
    text = (span or "").strip().strip("「」\"' ")
    text = re.sub(r"^(答案|答)[:：]\s*", "", text)
    text = text.splitlines()[0].strip() if text else ""
    if not text or text.upper() == "NONE" or text in {"无", "没有", "不知道", "未提到"}:
        return False
    if text in statement or text.rstrip("。") in statement:
        return True
    compact_span = _compact(text)
    compact_statement = _compact(statement)
    return bool(compact_span) and compact_span in compact_statement and len(compact_span) >= 2


def _named_value(statement: str) -> str:
    match = re.search(r"名叫([\u4e00-\u9fffA-Za-z0-9·]{1,12})", statement or "")
    return match.group(1) if match else ""


def _agent(statement: str) -> str:
    match = re.search(r"(?:女儿)?([\u4e00-\u9fff]{2,3})养了", statement or "")
    return match.group(1) if match else ""


def slot_from_fact(query: str, fact: dict) -> str:
    """从这一句里抄问句要的那段。抄不到就用事实里较短的取值。"""
    statement = _statement(fact)
    if not statement or clashes(query, fact) or off_topic(query, fact):
        return ""
    focus = _focus(query)
    if focus in {"闺女", "女儿", "儿子", "丫头"} and any(mark in query for mark in ("叫什么", "是谁", "名字")):
        match = re.search(r"(?:女儿|儿子)([\u4e00-\u9fff]{2,3})", statement)
        if match and not _echo(match.group(1), query):
            return match.group(1)
    if any(mark in query for mark in ("叫什么", "什么名字", "叫啥", "名字")) and "谁" not in query:
        named = _named_value(statement)
        if named and not _echo(named, query):
            return named
    if "谁" in query and ("养" in query or "养" in statement and "谁" in query):
        agent = _agent(statement)
        if agent and ("养" in query or "主人" in query) and not _echo(agent, query):
            return agent
    if any(mark in query for mark in ("磨", "打磨")) and "谁" in query and "打磨" in statement:
        craft = re.search(r"工匠([\u4e00-\u9fff]{1,8}?)(?=打磨|，|。|$)", statement)
        if craft and not _echo(craft.group(1), query):
            return craft.group(1)
    span = answer_span(query, statement)
    if span and _literal(span, statement) and not _echo(span, query):
        return span
    value = str(fact.get("value") or "").strip().rstrip("。")
    if _asked_heads(query) and not any(_head_in_statement(head, statement) for head in _asked_heads(query)):
        return ""
    if 1 <= len(value) <= 24 and value != statement.rstrip("。") and not _echo(value, query):
        if value in statement or _compact(value) in _compact(statement):
            return value
    return ""


def _prefer_short(query: str, span: str, fact: dict) -> str:
    short = slot_from_fact(query, fact)
    if short and len(short) < len(span) and _literal(short, _statement(fact)) and not _echo(short, query):
        return short
    return span


def _host_of(span: str, pool: list[dict]) -> dict | None:
    for fact in pool:
        if _literal(span, _statement(fact)):
            return fact
    return None


def accept_model_span(query: str, raw: str, pool: list[dict]) -> tuple[str, dict] | None:
    text = (raw or "").strip()
    text = re.sub(r"^(答案|答)[:：]\s*", "", text)
    text = text.splitlines()[0].strip() if text else ""
    if not text or text.upper().startswith("NONE") or text in {"无", "没有", "不知道"}:
        return None
    host = _host_of(text, pool)
    if host is None or clashes(query, host) or off_topic(query, host):
        return None
    slot = slot_from_fact(query, host)
    if slot and not _echo(slot, query):
        return slot, host
    if _echo(text, query):
        replacement = slot_from_fact(query, host)
        if replacement and not _echo(replacement, query):
            return replacement, host
        return None
    span = _prefer_short(query, text.rstrip("。"), host)
    if not span or _echo(span, query) or not _literal(span, _statement(host)):
        return None
    return span, host


def _brief(fact: dict) -> str:
    statement = _statement(fact)
    bits = []
    named = _named_value(statement)
    if named:
        bits.append(named)
    year = re.search(r"\d{3,4}年", statement)
    if year:
        bits.append(year.group(0))
    measure = re.search(r"[0-9０-９零〇一二三四五六七八九十百千万两]{1,8}(?:米|面)", statement)
    if measure:
        bits.append(measure.group(0))
    value = str(fact.get("value") or "").strip().rstrip("。")
    if value and len(value) <= 12 and value not in bits and value != statement.rstrip("。"):
        bits.append(value)
    if bits:
        return "、".join(dict.fromkeys(bits))
    return statement[:18].rstrip("，。")


def _topic(query: str, missing: str) -> str:
    if missing:
        return missing
    text = query or ""
    for filler in ("什么时候", "哪一年", "哪一天", "什么", "谁", "多少", "吗", "呢", "的", "是", "在", "有", "叫"):
        text = text.replace(filler, "")
    text = re.sub(r"[\s？?。，,]", "", text)
    return text[-8:] if text else "这件事"


def natural_refusal(query: str, pool: list[dict], missing: str = "") -> str:
    """说人话：记得哪一句，以及问句里哪一点没写过。"""
    if not has_cjk(query):
        return "I don't remember being told that."
    if "生日" in query:
        return "我不记得你告诉过我生日。"
    if pool and all(off_topic(query, fact) or clashes(query, fact) for fact in pool):
        head = _asked_heads(query)
        if head:
            return f"我不记得你告诉过我{head[0]}的事。"
        return "这件事你还没告诉过我。"
    owned = possessed_name_query(query)
    if owned:
        return f"你还没告诉过我你的{owned}叫什么。"
    if any(mark in query for mark in ("住哪", "住在", "住哪儿")) and not any("住" in _statement(fact) for fact in pool):
        return "我不记得你告诉过我住在哪里。"
    related = [fact for fact in pool if not clashes(query, fact)] or list(pool)
    if related:
        fact = related[0]
        name = ""
        for token in sorted(_link_tokens(fact), key=len, reverse=True):
            if token in query:
                name = token
                break
        if not name:
            name = str(fact.get("entity") or "").strip() or "这件事"
        remembered = _brief(fact)
        topic = _topic(query, missing)
        lead = "书里关于" if str(fact.get("source") or "") == "document" else "关于"
        if remembered and topic and topic not in remembered:
            return f"{lead}{name}我记得{remembered}，但没提到{topic}。"
        return f"{lead}{name}，这句话你还没告诉过我。"
    return "这件事你还没告诉过我。"


def _finish(span: str) -> str:
    text = span.strip()
    if text and text[-1] not in "。.!！？?":
        text += "。"
    return text


def read_memory(
    query: str,
    facts: list[dict],
    generate: Callable[[str, str], str] | None,
    query_vector: list[float] | None = None,
    fact_vectors: list[list[float]] | None = None,
) -> dict | None:
    """记忆题返回答案或自然的弃权。和记忆无关时返回 None，交给原来的路径。

    返回 {"text", "fact", "miss"}。miss 为真时不要再调用基座编造。
    """
    if not facts or not str(query or "").strip():
        return None
    pool, best = retrieve(query, facts, query_vector, fact_vectors)
    if not memory_question(query, facts, best, pool):
        return None
    hosts = _hosts(query, pool)
    if not hosts:
        return {"text": natural_refusal(query, pool), "fact": pool[0] if pool else None, "miss": True}
    missing = unsupported(query, hosts)
    if missing:
        return {"text": natural_refusal(query, hosts, missing), "fact": hosts[0], "miss": True}
    if generate is not None:
        lines = "\n".join(f"{index + 1}. {_statement(fact)}" for index, fact in enumerate(hosts))
        raw = generate(_READER, f"句子：\n{lines}\n问题：{query}\n答案：")
        accepted = accept_model_span(query, raw, hosts)
        if accepted:
            span, fact = accepted
            return {"text": _finish(span), "fact": fact, "miss": False}
    for fact in hosts:
        span = slot_from_fact(query, fact)
        if span:
            return {"text": _finish(span), "fact": fact, "miss": False}
    return {"text": natural_refusal(query, hosts), "fact": hosts[0], "miss": True}

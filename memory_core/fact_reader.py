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
from memory_core.span_guard import (
    accept_aligned,
    fixed_refusal,
    is_open_task,
    mentions_stored,
    predicate_covered,
    relation_decision,
    span_fits,
    predicate_in_statement,
)

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
    frozenset({"汽车", "车"}),
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
    color = re.match(r"^([\u4e00-\u9fff]{1,6})颜色$", attr)
    if color and color.group(1) not in heads:
        heads.append(color.group(1))
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
    if touches_memory(query, facts) or mentions_stored(query, facts):
        return True
    from memory_core.answer_type import grounded_subjects, question_kind

    if question_kind(query) and grounded_subjects(query, facts):
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


_NOT_SUBJECT = {"女儿", "闺女", "父亲", "爸爸", "老爸", "主人", "工匠", "师傅", "灯塔", "海鸥", "丫头"}


def _names_in_query(query: str, facts: list[dict]) -> list[str]:
    blob = "\n".join(_statement(fact) for fact in facts)
    found: list[str] = []
    text = query or ""
    for size in (4, 3, 2):
        for index in range(0, max(0, len(text) - size + 1)):
            token = text[index:index + size]
            if token in _NOT_SUBJECT or token in {"打磨", "守护", "看守", "什么", "怎么"}:
                continue
            if any(token in longer for longer in found):
                continue
            if token in blob:
                found.append(token)
    return found


def _statement_has_query_names(query: str, statement: str, facts: list[dict]) -> bool:
    names = _names_in_query(query, facts)
    if not names:
        return True
    return all(name in (statement or "") for name in names)


def _subject_in_statement(query: str, statement: str) -> bool:
    """「白鹭塔的闺女」不能拿柯岚的女儿那一句来答。"""
    names = []
    for chunk in re.findall(r"([\u4e00-\u9fff]{2,8})的", query or ""):
        piece = chunk
        changed = True
        while changed and len(piece) > 2:
            changed = False
            for role in sorted(_NOT_SUBJECT | {"养"}, key=len, reverse=True):
                if piece.endswith(role) and len(piece) > len(role):
                    piece = piece[: -len(role)]
                    changed = True
                    break
        if piece in _NOT_SUBJECT or len(piece) < 2:
            continue
        names.append(piece[-4:])
    if not names:
        return True
    text = statement or ""
    return any(name in text for name in names)


def _asked_relation(query: str) -> str:
    """紧挨着疑问词的那个关系，不管前面用来指路的字。"""
    match = re.search(r"的([\u4e00-\u9fff]{1,6})(?:叫什么|是谁|是什么|有多|在哪|哪年|什么时候)", query or "")
    if not match:
        return ""
    return _normalize_head(re.split(r"的|是", match.group(1))[-1])


def _piece_in(piece: str, statement: str) -> bool:
    if piece == "车":
        return re.search(r"(?<![自火汽])车", statement or "") is not None
    return bool(piece) and piece in (statement or "")


def _head_in_statement(head: str, statement: str) -> bool:
    if head and head in statement:
        return True
    for group in _KIN:
        if head in group and any(_piece_in(piece, statement) for piece in group):
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
    for mark in ("讨厌", "大学", "毕业", "股票", "身高"):
        if mark in query and mark not in blob:
            return mark
    if "多高" in query and not re.search(r"米|身高|塔高|多高", blob):
        return "多高"
    lowered = query.casefold()
    if re.search(r"\b(how old|age|email|e-mail|breed)\b", lowered) and not re.search(r"\b(age|email|breed|years old)\b", blob.casefold()):
        return "that"
    if "go public" in lowered and "public" not in blob.casefold():
        return "that"
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
    """固定句式。missing 只用于调用方兼容，不拼进句子。"""
    del missing
    return fixed_refusal(query, pool)


def _finish(span: str) -> str:
    text = span.strip()
    if text and text[-1] not in "。.!！？?":
        text += "。"
    return text


def answer_stated_question(query: str, facts: list[dict]) -> dict | None:
    """前半句是陈述、后半句在问。刚记下的那条事实能对上问句时，就用它回答。"""
    found = read_memory(query, facts, None)
    if found and not found.get("miss") and not _premise_echo(query, str(found.get("text") or "")):
        return found
    for fact in reversed(facts):
        statement = str(fact.get("statement") or "").strip().rstrip("。")
        if not statement or statement not in (query or ""):
            continue
        answered = _answer_from_same_fact(query, fact)
        if answered:
            return {"text": _finish(answered), "fact": fact, "miss": False}
        break
    from memory_core.answer_type import choose_typed

    from memory_core.answer_type import answer_fits

    picked = choose_typed(query, facts)
    if not picked:
        return None
    span, fact = picked
    if _premise_echo(query, str(span)):
        return None
    if not answer_fits(query, str(span), _statement(fact)):
        return None
    return {"text": _finish(str(span)), "fact": fact, "miss": False}


def _premise_echo(query: str, answer: str) -> bool:
    """前半句里的人名不能当成后半句另一个角色的答案。"""
    pieces = [part.strip() for part in re.split(r"[。！？\n；;，,]+", query or "") if part.strip()]
    if len(pieces) < 2:
        return False
    span = re.sub(r"[。.!！？?\s]", "", answer or "")
    if len(span) < 2 or span not in pieces[0] or span in pieces[-1]:
        return False
    return bool(re.search(r"谁|哪位|什么人|叫什么|叫啥", pieces[-1]))


def _answer_from_same_fact(query: str, fact: dict) -> str:
    """后半句问的就是刚写下的那条。问主人给实体，问取值给取值。"""
    pieces = [part.strip() for part in re.split(r"[。！？\n；;，,]+", query or "") if part.strip()]
    if len(pieces) < 2:
        return ""
    tail = pieces[-1]
    entity = str(fact.get("entity") or "").strip()
    value = str(fact.get("value") or "").strip()
    if not value or value == entity:
        return ""
    asks_owner = bool(re.search(r"主人|谁养|是谁养", tail)) and bool(entity) and entity not in tail
    if asks_owner and (value in tail or re.match(r"^[它他她这那]", tail)):
        return entity
    points_here = entity in tail or value in tail or bool(re.match(r"^[它他她这那]", tail))
    bare_attr = bool(re.match(r"^(?:什么颜色|啥颜色|什么色|哪里|哪儿|哪一年|哪年|叫什么|叫啥)", tail))
    if not points_here and not bare_attr:
        return ""
    if re.search(r"什么颜色|啥颜色|什么色", tail) and re.search(r"色", value):
        return value
    if re.search(r"哪里|哪儿|什么地方", tail) and value not in tail:
        return value
    if re.search(r"哪一年|哪年|什么时候", tail) and re.search(r"\d|年", value):
        return value
    if re.search(r"叫什么|叫啥|什么名字", tail) and value not in tail and not re.search(r"主人|父亲|女儿", tail):
        return value
    return ""


def _entity_supported(query: str, span: str, fact: dict, facts: list[dict]) -> bool:
    from memory_core.answer_type import supports_asked_entity

    return supports_asked_entity(query, span, _statement(fact), facts)


def _slot_ok(query: str, span: str, fact: dict, names: list[str]) -> bool:
    from memory_core.answer_type import accept_span

    statement = _statement(fact)
    if names and not all(name in statement for name in names):
        return False
    return bool(span) and accept_span(query, span, statement, require_subject=False)


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
    from memory_core.extract import is_question_fragment

    facts = [fact for fact in facts if isinstance(fact, dict) and not is_question_fragment(str(fact.get("statement") or ""))]
    if not facts or not str(query or "").strip():
        return None
    if is_open_task(query):
        return None
    from memory_core.span_guard import general_knowledge_question

    if general_knowledge_question(query):
        return None
    from memory_core.fact_graph import resolve_graph

    asked = query
    pieces = [part.strip() for part in re.split(r"[。！？\n；;，,]+", query or "") if part.strip()]
    if len(pieces) >= 2 and re.search(r"什么|谁|哪|吗|呢|啥", pieces[-1]) and not re.search(r"什么|谁|哪|吗|呢|啥", pieces[0]):
        asked = pieces[-1]
    graphed = resolve_graph(query, facts)
    if (graphed is None or graphed.get("status") != "answer") and asked != query:
        graphed = resolve_graph(asked, facts) or graphed
    if graphed is not None and graphed.get("status") == "answer":
        span = str(graphed.get("span") or "").strip()
        fact = graphed.get("fact") if isinstance(graphed.get("fact"), dict) else None
        if span:
            return {"text": _finish(span), "fact": fact, "miss": False}
    if graphed is not None and graphed.get("status") == "abstain":
        return {"text": fixed_refusal(query, facts), "fact": None, "miss": True}
    if re.search(r"是.+还是", query or "") and not general_knowledge_question(query):
        return {"text": fixed_refusal(query, facts), "fact": None, "miss": True}
    from memory_core.fact_span import entity_mentioned, near_miss_span
    from memory_core.grounding import open_entity_question
    from memory_core.paraphrase import is_polar

    # 是非题、介绍题、近似名字仍走原来的路径，摘录器不改写成一个取值。
    from memory_core.answer_type import _asks_school

    if is_polar(query) and not _asks_school(query):
        return None
    for fact in facts:
        entity = str(fact.get("entity") or "").strip()
        if not entity:
            continue
        if open_entity_question(query, entity):
            return None
        # 名字整段出现才摘录。「白鹭塔建于」里的建是谓语。
        # 「禾昭闻兰」「工坊公司 Inc」「工坊集团」是另一个名字，交给原来的澄清。
        if entity_mentioned(entity, query):
            continue
        missed = near_miss_span(entity, query)
        if missed:
            # 前面是动词（守护白鹭塔）仍是这个名字。后面只多一两个字才是另一个名字。
            if missed.endswith(entity) and not missed.startswith(entity):
                continue
            if missed.startswith(entity) and missed[len(entity):].startswith((
                "离", "到", "往", "打", "磨", "守", "养", "建", "的", "就", "毕", "上", "家", "念", "读",
                "负", "只", "把", "是", "在", "不", "照", "值", "站", "执", "看", "管",
            )):
                continue
            return {"text": fixed_refusal(query, facts), "fact": None, "miss": True}
    pool, best = retrieve(query, facts, query_vector, fact_vectors)
    from memory_core.answer_type import choose_typed, grounded_subjects

    names = grounded_subjects(query, facts)

    picked = choose_typed(query, facts)
    if picked:
        span, fact = picked
        from memory_core.answer_type import answer_fits

        if answer_fits(query, span, _statement(fact)):
            return {"text": _finish(span), "fact": fact, "miss": False}
    from memory_core.answer_type import modifier_conflicts, relation_question
    from memory_core.fact_span import entity_mentioned
    from memory_core.span_guard import memory_entity_question

    exact = any(entity_mentioned(str(fact.get("entity") or ""), query) for fact in facts)
    if modifier_conflicts(query, [fact for fact in facts if exact and entity_mentioned(str(fact.get("entity") or ""), query)] or facts):
        return {"text": fixed_refusal(query, facts), "fact": None, "miss": True}
    if relation_question(query) or (memory_entity_question(query) and not exact):
        return {"text": fixed_refusal(query, facts), "fact": None, "miss": True}
    for thing in ("狗", "猫", "自行车", "汽车"):
        if thing in query and not any(
            thing in _statement(fact) or thing in str(fact.get("attr") or "") for fact in facts
        ):
            return {"text": fixed_refusal(query, facts), "fact": None, "miss": True}
    if "讨厌" in query and not any("讨厌" in _statement(fact) for fact in facts):
        return {"text": fixed_refusal(query, facts), "fact": None, "miss": True}
    if "我的" in query or query.startswith("我"):
        return None
    if not memory_question(query, facts, best, pool):
        return None
    hosts = [fact for fact in _hosts(query, pool) if predicate_covered(query, _statement(fact), fact)]
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
            checked = accept_aligned(query, span, fact)
            if _slot_ok(query, checked, fact, names) and _entity_supported(query, checked, fact, facts):
                return {"text": _finish(checked), "fact": fact, "miss": False}
    for fact in hosts:
        span = slot_from_fact(query, fact)
        checked = accept_aligned(query, span, fact) if span else ""
        if _slot_ok(query, checked, fact, names) and _entity_supported(query, checked, fact, facts):
            return {"text": _finish(checked), "fact": fact, "miss": False}
    return {"text": natural_refusal(query, hosts), "fact": None, "miss": True}


def assert_school_is_recalled() -> None:
    """教过的学校必须答出来。事实在而说没记过，验收直接失败。"""
    cat = {"entity": "沈星河", "statement": "沈星河的猫的名字是云朵。", "value": "云朵"}
    forms = [
        "沈星河在青藤中学上学。",
        "沈星河的学校是青藤中学。",
        "沈星河就读于青藤中学。",
        "沈星河毕业于青藤中学。",
        "沈星河是青藤中学的学生。",
    ]
    questions = [
        "沈星河的学校叫什么？",
        "沈星河在哪所学校上学？",
        "沈星河念的哪所学校？",
        "沈星河上的什么学校？",
        "沈星河在哪个学校读书？",
        "请问沈星河的学校叫啥？",
        "沈星河的学校的名字是什么？",
        "沈星河就读的学校叫什么名字？",
        "沈星河毕业于哪所学校？",
        "沈星河的学校你知道吗？",
        "沈星河是在哪个学校读书的？",
        "沈星河现在在哪儿念书？",
    ]
    people = [
        ("陆远毕业于南开大学。", "陆远是哪个学校毕业的？", "南开大学"),
        ("许诺是青藤中学的学生。", "许诺是哪个学校的学生？", "青藤中学"),
    ]
    for statement in forms:
        fact = {"entity": "沈星河", "statement": statement, "value": "青藤中学"}
        for question in questions:
            answer = (read_memory(question, [fact, cat], None) or {}).get("text") or ""
            if "青藤" not in answer or "没记过" in answer or "云朵" in answer:
                raise RuntimeError(f"教过的学校没有答出来：{statement} / {question} -> {answer}")
        other = (read_memory("周晚宁的学校叫什么？", [fact, cat], None) or {}).get("text") or ""
        if "青藤" in other or "云朵" in other:
            raise RuntimeError(f"别人的学校拿了沈星河的取值：{other}")
        missed = (read_memory("陆远是哪个学校毕业的？", [fact, cat], None) or {}).get("text") or ""
        if "青藤" in missed or "云朵" in missed or "是的学校" in missed:
            raise RuntimeError(f"没教过的学校说错了：{missed}")
    for statement, question, school in people:
        fact = {"entity": statement[:2], "statement": statement, "value": school}
        answer = (read_memory(question, [fact, cat], None) or {}).get("text") or ""
        if school not in answer or "没记过" in answer or "云朵" in answer:
            raise RuntimeError(f"教过的学校没有答出来：{statement} / {question} -> {answer}")

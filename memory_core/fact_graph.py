"""从已存事实抽出实体到实体的边，再按问句的每一跳来走。

走得通才回答。某一跳没有正好连接这两边的事实，就弃权，不借用链上另一个人或另一种属性。
问句不像一条能走的链时返回 None，交给原来的摘录。
"""
from __future__ import annotations

import re
from typing import Any

from memory_core.extract import _ZH_COLOR, without_tag_question

_KIN = (
    ("父亲", "father"),
    ("爸爸", "father"),
    ("老爸", "father"),
    ("她爸", "father"),
    ("他爸", "father"),
    ("母亲", "mother"),
    ("妈妈", "mother"),
    ("女儿", "daughter"),
    ("儿子", "son"),
    ("哥哥", "brother"),
    ("弟弟", "brother"),
    ("姐姐", "sister"),
    ("妹妹", "sister"),
    ("兄弟", "brother"),
    ("叔叔", "uncle"),
    ("爷爷", "grandfather"),
    ("妻子", "spouse"),
    ("丈夫", "spouse"),
    ("太太", "spouse"),
    ("老婆", "spouse"),
    ("老公", "spouse"),
)
_HOP_WORDS = _KIN + (
    ("养的", "pet"),
    ("的猫", "pet"),
    ("的狗", "pet"),
    ("的鸟", "pet"),
    ("猫", "pet"),
    ("狗", "pet"),
    ("鸟", "pet"),
    ("看守的", "keeps"),
    ("守护的", "keeps"),
    ("值守的", "keeps"),
)
_DEFER = ("透镜", "灯塔", "海鸥", "主人", "师傅", "工匠", "设计", "建造", "打磨", "霜降", "特产", "国籍", "哪国", "电灯")
_OBJECT_ALIAS = (
    frozenset({"汽车", "车"}),
    frozenset({"自行车", "单车"}),
    frozenset({"猫", "猫咪"}),
    frozenset({"狗", "小狗"}),
)
_TERMINALS = (
    (r"是什么颜色|啥颜色|什么颜色|什么色", "color"),
    (r"是什么牌子|是什么品牌|什么牌子|什么品牌|哪个牌子|哪个品牌", "brand"),
    (r"在哪(?:里|儿)?上班|在哪(?:里|儿)?工作|哪里上班|哪儿工作|哪里工作", "workplace"),
    (r"哪一年拆除|哪年拆除|何时拆除|什么时候拆除|哪年拆的|哪一年拆", "demolished"),
    (r"建于哪一年|哪一年建的|哪年建成|哪年建的|是哪一年建的", "built"),
    (r"哪年去世|哪一年去世|何时去世|哪年逝世|死于哪一年|哪年死的", "died"),
    (r"哪年出生|哪一年出生|是哪年出生|生于哪一年", "born"),
    (r"叫什么名字|叫什么|叫啥|是谁|什么名字", "identity"),
)


def _statement(fact: dict) -> str:
    return str(fact.get("statement") or fact.get("value") or "")


def _objects_align(left: str, right: str) -> bool:
    left = re.sub(r"^(?:那|这|一)?(?:辆|只|个|座)", "", left or "")
    right = re.sub(r"^(?:那|这|一)?(?:辆|只|个|座)", "", right or "")
    if not left or not right or left == right:
        return True
    if any(left in group and right in group for group in _OBJECT_ALIAS):
        return True
    return False


def _color_value(value: str) -> bool:
    piece = re.sub(r"的$", "", (value or "").strip())
    return bool(piece) and bool(_ZH_COLOR.match(piece))


def build_edges(facts: list[dict]) -> list[tuple[str, str, str, str, dict]]:
    """(起点, 关系, 终点, 事物, 事实)。事物只在颜色和牌子上用来区分车和自行车。"""
    edges: list[tuple[str, str, str, str, dict]] = []

    def add(src: str, rel: str, dst: str, fact: dict, obj: str = "") -> None:
        src, dst, obj = src.strip(), dst.strip().rstrip("。"), obj.strip()
        if not src or not dst or src == dst:
            return
        edges.append((src, rel, dst, obj, fact))

    for fact in facts:
        if not isinstance(fact, dict) or fact.get("superseded"):
            continue
        text = _statement(fact)
        for match in re.finditer(
            r"([\u4e00-\u9fff]{2,4})的(女儿|儿子|父亲|母亲|爸爸|妈妈|哥哥|弟弟|姐姐|妹妹|妻子|丈夫)(?:是|叫)?([\u4e00-\u9fff]{2,4})",
            text,
        ):
            rel = dict(_KIN).get(match.group(2), "")
            if not rel:
                continue
            add(match.group(1), rel, match.group(3), fact)
            if rel == "daughter":
                add(match.group(3), "father", match.group(1), fact)
            elif rel == "son":
                add(match.group(3), "father", match.group(1), fact)
            elif rel == "father":
                add(match.group(3), "child", match.group(1), fact)
        pet = re.search(r"([\u4e00-\u9fff]{2,4})养了.{0,12}名叫([\u4e00-\u9fff]{1,8})", text)
        if pet:
            add(pet.group(1), "pet", pet.group(2), fact)
            add(pet.group(2), "owner", pet.group(1), fact)
        named_pet = re.search(r"([\u4e00-\u9fff]{2,4})的(猫|狗|鸟)叫([\u4e00-\u9fff]{1,8})", text)
        if named_pet:
            add(named_pet.group(1), "pet", named_pet.group(3), fact)
        work = re.search(r"([\u4e00-\u9fff]{2,4})在([\u4e00-\u9fff]{2,16})(?:上班|工作)", text)
        if work:
            add(work.group(1), "workplace", work.group(2), fact)
        kept = re.search(
            r"([\u4e00-\u9fff]{2,4})(?:看守|守护|值守)的[\u4e00-\u9fff]{0,6}名叫([\u4e00-\u9fff]{2,8})",
            text,
        )
        if kept:
            add(kept.group(1), "keeps", kept.group(2), fact)
        built = re.search(r"([\u4e00-\u9fff]{2,8})建于(\d{3,4}年)", text)
        named_built = re.search(r"名叫([\u4e00-\u9fff]{2,8}).{0,8}建于(\d{3,4}年)", text)
        if named_built:
            add(named_built.group(1), "built", named_built.group(2), fact)
        elif built:
            add(built.group(1), "built", built.group(2), fact)
        demolished = re.search(r"([\u4e00-\u9fff]{2,8})(?:于)?(\d{3,4}年)(?:被)?拆除", text)
        if demolished:
            add(demolished.group(1), "demolished", demolished.group(2), fact)
        died = re.search(r"([\u4e00-\u9fff]{2,4})(?:死于|去世于|逝世于)(\d{3,4}年)", text)
        if died:
            add(died.group(1), "died", died.group(2), fact)
        born = re.search(r"([\u4e00-\u9fff]{2,4})生于(\d{3,4}年)", text)
        if born:
            add(born.group(1), "born", born.group(2), fact)
        brand = re.search(
            r"([\u4e00-\u9fff]{2,8})的([\u4e00-\u9fff]{1,8})(?:品牌|牌子)是([\u4e00-\u9fffA-Za-z0-9]{1,16})",
            text,
        )
        if brand:
            add(brand.group(1), "brand", brand.group(3), fact, brand.group(2))
        for match in re.finditer(r"([\u4e00-\u9fff]{2,8})的([\u4e00-\u9fff]{1,8})颜色是([\u4e00-\u9fff]{1,8})", text):
            add(match.group(1), "color", re.sub(r"的$", "", match.group(3)), fact, match.group(2))
        for match in re.finditer(r"([\u4e00-\u9fff]{2,8})的([\u4e00-\u9fff]{1,8})是([\u4e00-\u9fff]{1,8})", text):
            value = re.sub(r"的$", "", match.group(3))
            if match.group(2) in {"女儿", "儿子", "父亲", "母亲", "爸爸", "妈妈", "品牌", "牌子"}:
                continue
            if _color_value(value):
                add(match.group(1), "color", value, fact, match.group(2))
        height = re.search(r"([\u4e00-\u9fff]{2,8}).{0,8}(?:高|塔高)([0-9一二三四五六七八九十百千两]{1,8}米)", text)
        if height and "建于" not in text[max(0, height.start() - 2): height.end()]:
            add(height.group(1), "height", height.group(2), fact)
    return edges


def _nodes(edges: list[tuple[str, str, str, str, dict]]) -> list[str]:
    found: set[str] = set()
    for src, _rel, dst, _obj, _fact in edges:
        for name in (src, dst):
            if re.fullmatch(r"[\u4e00-\u9fff]{2,8}", name):
                found.add(name)
    return sorted(found, key=len, reverse=True)


def _start_name(text: str, nodes: list[str]) -> str:
    hits = []
    for name in nodes:
        index = text.find(name)
        if index >= 0:
            hits.append((index, -len(name), name))
    if not hits:
        return ""
    hits.sort()
    return hits[0][2]


def _parse_hops(body: str, start: str, terminal: str) -> list[str] | None:
    """返回关系列表。出现认不出的中间词时返回 None，避免把别人的属性安到起点上。"""
    rest = body[body.find(start) + len(start):] if start and start in body else body
    hops: list[str] = []
    words = sorted(_HOP_WORDS, key=lambda item: len(item[0]), reverse=True)
    while rest:
        rest = rest.lstrip("的")
        if not rest:
            break
        matched = ""
        rel = ""
        for word, kind in words:
            if rest.startswith(word):
                matched = word
                rel = kind
                break
        if matched:
            if hops and rel == hops[-1]:
                rest = rest[len(matched):]
                continue
            hops.append(rel)
            rest = rest[len(matched):]
            continue
        noun = re.match(r"[\u4e00-\u9fff]{1,8}", rest)
        if not noun:
            return None
        if not hops and terminal in {"color", "brand"}:
            rest = rest[noun.end():]
            continue
        if hops and hops[-1] in {"keeps", "pet"}:
            rest = rest[noun.end():]
            continue
        return None
    return hops


def _attribute_object(body: str, start: str) -> str:
    rest = body[body.find(start) + len(start):] if start and start in body else ""
    rest = rest.lstrip("的")
    rest = re.sub(r"^(?:那|这|一)?(?:辆|只|个|座)", "", rest)
    return rest.strip("的 ")


def _choice(text: str, edges: list[tuple[str, str, str, str, dict]]) -> dict[str, Any] | None:
    matched = re.match(r"^(?P<head>.+?)是(?P<a>[^，,。？?]{1,16})还是(?P<b>[^，,。？?]{1,16})$", text)
    if not matched:
        return None
    head, left, right = matched.group("head"), matched.group("a"), matched.group("b")
    nodes = _nodes(edges)
    start = _start_name(head, nodes)
    if not start:
        return {"status": "abstain"}
    want = ""
    if any(mark in head for mark in ("颜色", "色")):
        want = "color"
    elif any(mark in head for mark in ("牌子", "品牌")):
        want = "brand"
    obj = _attribute_object(head, start)
    hits: list[tuple[str, dict]] = []
    for src, rel, dst, edge_obj, fact in edges:
        if src != start or rel not in {"color", "brand"}:
            continue
        if want and rel != want:
            continue
        if obj and edge_obj and not _objects_align(obj, edge_obj):
            continue
        def _plain(value: str) -> str:
            return re.sub(r"(?:色|的)+$", "", value)

        if _plain(dst) and _plain(dst) in {_plain(left), _plain(right)}:
            hits.append((dst, fact))
    unique = []
    for dst, fact in hits:
        if all(dst != old for old, _fact in unique):
            unique.append((dst, fact))
    if len(unique) == 1:
        return {"status": "answer", "span": unique[0][0], "fact": unique[0][1]}
    return {"status": "abstain"}


def _parse(query: str, edges: list[tuple[str, str, str, str, dict]]) -> dict[str, Any] | None:
    text = without_tag_question(query or "").strip().rstrip("？?。")
    if not text or any(mark in text for mark in _DEFER):
        return None
    choice = _choice(text, edges)
    if choice is not None:
        return choice
    terminal = ""
    body = text
    for pattern, kind in _TERMINALS:
        matched = re.search(pattern, text)
        if matched:
            terminal = kind
            body = text[: matched.start()]
            break
    if not terminal:
        return None
    if "谁" in text and not re.search(r"的[\u4e00-\u9fff]{1,4}(?:是谁|叫什么|叫啥)", text):
        return None
    nodes = _nodes(edges)
    start = _start_name(body or text, nodes)
    if not start:
        return None
    hops = _parse_hops(body, start, terminal)
    if hops is None:
        # 认不出的身份说法交给原来的摘录。「同事在哪里上班」这种属性不能退回去借用起点自己的取值。
        if terminal == "identity":
            return None
        return {"status": "abstain"}
    obj = _attribute_object(body, start) if terminal in {"color", "brand"} and not hops else ""
    if terminal in {"color", "brand"} and not hops and not obj:
        return None
    return {"status": "chain", "start": start, "hops": hops, "terminal": terminal, "object": obj}


def _walk(start: str, hops: list[str], edges: list[tuple[str, str, str, str, dict]]) -> tuple[str, dict] | None:
    node = start
    fact: dict = {}
    for hop in hops:
        nxt = [(dst, host) for src, rel, dst, _obj, host in edges if src == node and rel == hop]
        if len(nxt) != 1:
            return None
        node, fact = nxt[0]
    return node, fact


def _attribute(
    node: str,
    terminal: str,
    obj: str,
    edges: list[tuple[str, str, str, str, dict]],
) -> tuple[str, dict] | None:
    found = [
        (dst, host)
        for src, rel, dst, edge_obj, host in edges
        if src == node and rel == terminal and (not obj or not edge_obj or _objects_align(obj, edge_obj))
    ]
    if obj:
        found = [
            (dst, host)
            for src, rel, dst, edge_obj, host in edges
            if src == node and rel == terminal and edge_obj and _objects_align(obj, edge_obj)
        ]
    if len(found) != 1:
        return None
    return found[0]


def resolve_graph(query: str, facts: list[dict]) -> dict[str, Any] | None:
    """答得了就给取值。问句是一条链但某一跳没有边，就弃权。不像链就返回 None。"""
    rows = [fact for fact in facts if isinstance(fact, dict)]
    edges = build_edges(rows)
    if not edges:
        return None
    parsed = _parse(query, edges)
    if not parsed:
        return None
    if parsed.get("status") in {"answer", "abstain"}:
        return parsed
    walked = _walk(parsed["start"], parsed["hops"], edges)
    if walked is None:
        return {"status": "abstain"}
    node, fact = walked
    terminal = parsed["terminal"]
    if terminal == "identity":
        if not parsed["hops"]:
            return None
        return {"status": "answer", "span": node, "fact": fact}
    obj = parsed.get("object") or ""
    if terminal in {"color", "brand"} and obj:
        aligned = [
            rel
            for src, rel, _dst, edge_obj, _host in edges
            if src == node and edge_obj and _objects_align(obj, edge_obj) and rel in {"color", "brand"}
        ]
        if not aligned:
            return None
        if terminal not in aligned:
            return {"status": "abstain"}
    picked = _attribute(node, terminal, obj, edges)
    if picked is None:
        return {"status": "abstain"}
    return {"status": "answer", "span": picked[0], "fact": picked[1]}

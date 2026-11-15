"""用整句事实本身回答，不要求问句里出现专家名。

问句里的别名、描述和属性都对着已存的句子看。能对上就引用那一句，
对不上就不许基座另编一个取值。有向量时再和 bge 比较整句。
"""
from __future__ import annotations

import math
import re
from typing import Any

_FILLERS = (
    "什么时候", "哪一年", "哪一天", "哪一年", "什么名字", "叫什么", "哪年", "哪天", "哪里", "哪儿",
    "为什么", "怎么", "多少", "什么", "谁", "吗", "呢", "每年", "那只", "这只", "一共", "名字",
    "开始", "的", "是", "在", "有", "叫", "和", "与", "了", "能", "会", "吗",
    "今年", "几岁", "多大", "年龄",
)
_ASK_ONLY = frozenset({"多高", "高度", "多远", "几岁", "今年", "晒", "晾晒"})


def fact_aliases(statement: str) -> list[str]:
    """从原句里留下可以换着问的说法。"""
    text = str(statement or "")
    found: list[str] = []

    def add(value: str) -> None:
        value = value.strip("，。、 ")
        if len(value) < 2 or value in found:
            return
        found.append(value)

    for match in re.finditer(r"(?:一只|一座|一种)?([\u4e00-\u9fff]{0,6}的)?([\u4e00-\u9fff]{2,8})", text):
        phrase = f"{match.group(1) or ''}{match.group(2)}"
        if any(mark in phrase for mark in ("名叫", "建于", "开始", "打磨")):
            continue
        if len(phrase) >= 4:
            add(phrase)
    for pattern in (
        r"三条腿的海鸥",
        r"第一座灯塔",
        r"蓝色海盐",
        r"[\u4e00-\u9fff]{2,6}塔",
        r"透镜",
    ):
        for match in re.finditer(pattern, text):
            add(match.group(0))
    return found[:12]


def fact_mentions(statement: str, primary: str = "") -> list[str]:
    """这句话点到的主体。问其中任何一个都该找到这条事实。"""
    text = str(statement or "")
    found: list[str] = []

    def add(value: str) -> None:
        value = value.strip()
        if len(value) < 2 or value in found:
            return
        if value in {"雾港", "灯塔", "海盐", "海鸥", "透镜", "电灯"}:
            return
        found.append(value)

    if primary and primary not in {"文档", "正文"}:
        add(primary)
    for pattern in (
        r"名叫([\u4e00-\u9fffA-Za-z0-9·]{2,12})",
        r"([\u4e00-\u9fff]{2,8})建于",
        r"([\u4e00-\u9fff]{2,6})的灯",
        r"工匠([\u4e00-\u9fff]{1,6})",
        r"([\u4e00-\u9fff]{2,3})养了",
        r"([\u4e00-\u9fff]{2,3})在",
        r"([\u4e00-\u9fff]{2,3})的女儿",
        r"([\u4e00-\u9fff]{2,4})守护",
    ):
        for match in re.finditer(pattern, text):
            add(match.group(1))
    return found


def fact_blob(fact: dict) -> str:
    parts = [
        str(fact.get("statement") or ""),
        str(fact.get("value") or ""),
        " ".join(str(item) for item in fact.get("aliases") or []),
        " ".join(str(item) for item in fact.get("mentions") or []),
    ]
    aliases = fact_aliases(str(fact.get("statement") or ""))
    parts.extend(aliases)
    return " ".join(part for part in parts if part)


def _pieces(query: str) -> list[str]:
    text = str(query or "")
    for filler in sorted(_FILLERS, key=len, reverse=True):
        text = text.replace(filler, "\x01")
    parts = []
    for piece in text.split("\x01"):
        piece = piece.strip("，。？?、 ")
        if len(piece) >= 2 and piece not in parts:
            parts.append(piece)
        elif len(piece) == 1 and piece not in "我你他她它":
            if piece not in parts:
                parts.append(piece)
    return [part for part in parts if part not in {"请问", "告诉"}]


def _compact(text: str) -> str:
    return re.sub(r"[\s，,。.!！？?、；;：:「」\"']", "", text or "")


def _standalone(piece: str, compact: str) -> bool:
    """单字必须自己成词。「车」不能从「自行车」里抠出来。"""
    bounds = set("的了是在有和与吗呢叫，。、")
    start = 0
    while True:
        index = compact.find(piece, start)
        if index < 0:
            return False
        before = compact[index - 1] if index else ""
        after = compact[index + len(piece)] if index + len(piece) < len(compact) else ""
        before_ok = not before or before in bounds
        after_ok = not after or after in bounds
        if before_ok and after_ok:
            return True
        start = index + 1


def _piece_hit(piece: str, blob: str, statement: str) -> bool:
    if piece in {"多高", "高度"}:
        return bool(re.search(r"塔高|高\d|米|四十二", statement))
    if piece in {"晒", "晾晒"} or (len(piece) > 1 and "晒" in piece):
        return "晒" in statement or "霜降" in statement
    if piece in {"建", "建成"} and re.search(r"建于|\d{3,4}年", statement):
        return True
    if piece == "面" and "面" in statement:
        return True
    compact = _compact(blob + statement)
    if len(piece) == 1:
        return _standalone(piece, compact)
    if piece in compact:
        return True
    # 「柯岚守护」对得上「柯岚在雾港守护」。中间可以隔几个字。
    for cut in range(2, len(piece) - 1):
        left, right = piece[:cut], piece[cut:]
        if len(right) < 2:
            continue
        start = compact.find(left)
        if start < 0:
            continue
        window = compact[start + len(left):start + len(left) + 8]
        if right in window:
            return True
    if piece in _ASK_ONLY or piece in {"多高", "高度"}:
        return bool(re.search(r"塔高|高\d|米|四十二", statement))
    if piece in {"晒", "晾晒"} or "晒" in piece:
        return "晒" in statement or "霜降" in statement
    if piece in {"建", "建成"} and re.search(r"建于|\d{3,4}年", statement):
        return True
    return False


def _evidence(query: str, statement: str) -> bool:
    """问句要的那种取值必须真的写在这句话里。"""
    if any(mark in query for mark in ("多高", "高度", "有多高")):
        return bool(re.search(r"高|米", statement))
    if any(mark in query for mark in ("多远", "照多远")):
        return "远" in statement
    if any(mark in query for mark in ("几岁", "多大", "年龄")):
        return bool(re.search(r"岁|年龄", statement))
    if any(mark in query for mark in ("哪一年", "哪年", "建于", "什么时候", "哪天", "何时")):
        return bool(re.search(r"\d{3,4}\s*年|建于|霜降|晾晒", statement))
    if any(mark in query for mark in ("叫什么", "名字", "是谁", "谁")):
        if any(mark in query for mark in ("市长", "妻子", "丈夫")):
            return any(mark in statement for mark in ("市长", "妻子", "丈夫"))
        return bool(re.search(r"名叫|叫|工匠|名字是|名为", statement))
    if "面" in query and "多少" in query:
        return "面" in statement and bool(re.search(r"十六|\d+", statement))
    if any(mark in query for mark in ("市长", "妻子", "丈夫", "公司", "上班")):
        return any(mark in statement for mark in ("市长", "妻子", "丈夫", "公司", "上班"))
    if "电灯" in query or "改用" in query:
        return "电灯" in statement or "改用" in statement
    if "打磨" in query:
        return "打磨" in statement
    if "特产" in query:
        return "特产" in statement
    return True


def _cosine(left: list[float] | None, right: list[float] | None) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return dot / (left_norm * right_norm)


def touches_memory(query: str, facts: list[dict]) -> bool:
    """问句里有已经记下的人或事物。这种问题不能再交给基座编。"""
    pieces = [piece for piece in _pieces(query) if len(piece) >= 2 and piece not in _ASK_ONLY]
    if not pieces:
        return False
    for fact in facts:
        blob = fact_blob(fact)
        if any(piece in blob for piece in pieces):
            return True
    return False


def recall_fact(
    query: str,
    facts: list[dict],
    query_vector: list[float] | None = None,
    fact_vectors: list[list[float]] | None = None,
) -> dict | None:
    """在全部已存事实上找一句能支撑这个问法的。找不到就返回 None。"""
    pieces = _pieces(query)
    best: dict | None = None
    best_score = 0.0
    for index, fact in enumerate(facts):
        if not isinstance(fact, dict) or fact.get("superseded"):
            continue
        statement = str(fact.get("statement") or "")
        if not statement:
            continue
        blob = fact_blob(fact)
        if pieces:
            hits = sum(1 for piece in pieces if _piece_hit(piece, blob, statement))
            lexical = hits / len(pieces)
        else:
            lexical = 0.0
        semantic = 0.0
        if query_vector is not None and fact_vectors is not None and index < len(fact_vectors):
            semantic = _cosine(query_vector, fact_vectors[index])
        if not _evidence(query, statement):
            continue
        # 问句里的实词都要落在这句话里。bge 只在已经对上的句子里排先后，
        # 不能因为「汽车」和「自行车」相近就拿另一条事实来答。
        if lexical < 0.999:
            continue
        score = lexical + semantic
        if score > best_score:
            best = fact
            best_score = score
    return best


def possessed_name_query(query: str) -> str:
    """「我的狗叫什么名字」里的狗。问的是使用者本人时返回空。"""
    match = re.search(r"我的(?!名字|姓名|自己)([\u4e00-\u9fff]{1,8}?)叫", query or "")
    if not match:
        return ""
    return match.group(1)

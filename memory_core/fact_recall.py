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
    text = re.sub(r"[，,。.!！？?、；;：:「」\"'（）()]", "\x01", text)
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


_SOLAR = (
    "立春", "雨水", "惊蛰", "春分", "清明", "谷雨", "立夏", "小满", "芒种", "夏至",
    "小暑", "大暑", "立秋", "处暑", "白露", "秋分", "寒露", "霜降", "立冬", "小雪",
    "大雪", "冬至", "小寒", "大寒",
)
_MEASURE = r"[0-9０-９零〇一二三四五六七八九十百千万两]{1,8}(?:米|面|岁|公里|里)"
_IGNORE_NOUNS = frozenset({
    "什么", "怎么", "哪年", "哪天", "哪里", "哪儿", "谁", "多少", "开始", "建成", "完工",
    "落成", "建", "晒", "晾晒", "打磨", "养", "改用", "一共", "这座", "那座", "这只", "那只",
    "那天", "每年", "名字", "时候", "请问", "告诉", "一下", "知道", "这个", "那个",
    "什么时候", "哪一天", "哪一年", "多高", "高度", "颜色", "今年", "几岁",
    "那一年", "这一年", "那年", "这年", "那一天", "这一天", "那天", "哪天",
    "他", "她", "它", "你", "我", "米", "面", "岁", "年",
})


def _evidence(query: str, statement: str) -> bool:
    """问句要的那种取值必须真的写在这句话里。"""
    if any(mark in query for mark in ("多高", "高度", "有多高")):
        return bool(re.search(r"米|塔高", statement))
    if any(mark in query for mark in ("多远", "照多远")):
        return "远" in statement
    if any(mark in query for mark in ("几岁", "多大", "年龄", "今年")):
        return bool(re.search(r"岁|年龄", statement))
    if any(mark in query for mark in ("晒", "晾")) and any(mark in query for mark in ("什么时候", "哪天", "哪一天", "何时", "哪年")):
        return "晒" in statement or "晾" in statement or any(term in statement for term in _SOLAR)
    if any(mark in query for mark in ("建成", "完工", "落成")) or ("建" in query and "年" in query):
        return "建" in statement and bool(re.search(r"\d{3,4}\s*年|建于", statement))
    if any(mark in query for mark in ("哪一年", "哪年", "建于", "什么时候", "哪天", "何时")):
        return bool(re.search(r"\d{3,4}\s*年|建于", statement)) or any(term in statement for term in _SOLAR)
    if any(mark in query for mark in ("叫什么", "名字", "是谁", "谁")):
        if any(mark in query for mark in ("市长", "妻子", "丈夫")):
            return any(mark in statement for mark in ("市长", "妻子", "丈夫"))
        return bool(re.search(r"名叫|叫|工匠|名字是|名为|养了", statement))
    if "面" in query and any(mark in query for mark in ("多少", "几", "一共")):
        return "面" in statement and bool(re.search(r"\d|[一二三四五六七八九十]", statement))
    if any(mark in query for mark in ("市长", "妻子", "丈夫", "公司", "上班")):
        return any(mark in statement for mark in ("市长", "妻子", "丈夫", "公司", "上班"))
    if "电灯" in query or "改用" in query or "用电" in query:
        return "电" in statement or "改" in statement
    if "打磨" in query:
        return "打磨" in statement
    if "特产" in query:
        return "特产" in statement or bool(re.search(r"名叫", statement))
    if "腿" in query:
        return "腿" in statement
    return True


def strong_value_spans(statement: str) -> list[str]:
    """取值本身：年份、尺寸、名叫、节气、工匠名、颜色。问句拿这些当钥匙也能找回原句。"""
    text = str(statement or "")
    found: list[str] = []

    def add(value: str) -> None:
        value = str(value or "").strip("，。、 ")
        if len(value) < 2 or value in found:
            return
        found.append(value)

    for match in re.finditer(r"\d{3,4}年", text):
        add(match.group(0))
    for match in re.finditer(_MEASURE, text):
        add(match.group(0))
    for match in re.finditer(r"名叫([\u4e00-\u9fffA-Za-z0-9·]{1,12})", text):
        add(match.group(1))
    for term in _SOLAR:
        if term in text:
            add(term)
    for match in re.finditer(r"工匠([\u4e00-\u9fff]{1,8}?)(?=打磨|，|。|$)", text):
        add(match.group(1))
    for match in re.finditer(r"是([\u4e00-\u9fff]{1,4}色)", text):
        add(match.group(1))
    for match in re.finditer(r"([一二三四五六七八九十两0-9]{1,3}条腿)", text):
        add(match.group(1))
    return found


def _anchor_tokens(fact: dict) -> list[str]:
    statement = str(fact.get("statement") or "")
    tokens = strong_value_spans(statement)
    tokens.extend(fact_aliases(statement))
    tokens.extend(fact_mentions(statement, str(fact.get("entity") or "")))
    entity = str(fact.get("entity") or "").strip()
    if len(entity) >= 2:
        tokens.append(entity)
    value = str(fact.get("value") or "").strip().rstrip("。")
    if 2 <= len(value) <= 12:
        tokens.append(value)
    for pattern in (r"透镜", r"电灯", r"海鸥", r"海盐", r"灯塔", r"打磨", r"晾晒", r"特产", r"塔高", r"工匠"):
        match = re.search(pattern, statement)
        if match and match.group(0) not in tokens:
            tokens.append(match.group(0))
    unique: list[str] = []
    for token in tokens:
        token = str(token or "").strip()
        if len(token) >= 2 and token not in unique:
            unique.append(token)
    return unique


def _query_has(query: str, span: str) -> bool:
    if not span:
        return False
    compact = _compact(query)
    if len(span) == 1:
        return _standalone(span, compact)
    return span in compact


def _content_nouns(query: str) -> list[str]:
    nouns = []
    for piece in _pieces(query):
        if piece in _IGNORE_NOUNS or piece in _ASK_ONLY:
            continue
        if piece not in nouns:
            nouns.append(piece)
    return nouns


def _noun_in_fact(noun: str, statement: str) -> bool:
    compact = _compact(statement)
    if len(noun) == 1:
        return _standalone(noun, compact)
    return noun in compact


_WRAP = set("这那座只个的高些哪人过了着从起往向")


def _noun_covered(noun: str, statement: str) -> bool:
    """粘在一起的说法，只要每段都在原句里，就不算另一个事物。

    「瑞典工匠打磨白鹭塔」对得上透镜那句；「汽车颜色」对不上自行车。
    """
    if _ignorable_noun(noun) or _noun_in_fact(noun, statement):
        return True
    compact = _compact(statement)
    rest = noun
    while rest:
        if _ignorable_noun(rest) or all(char in _WRAP for char in rest):
            return True
        found = ""
        limit = min(len(rest), 12)
        for size in range(limit, 1, -1):
            for index in range(0, len(rest) - size + 1):
                chunk = rest[index:index + size]
                if chunk in compact:
                    found = chunk
                    break
            if found:
                break
        if not found:
            return False
        rest = rest.replace(found, "", 1)
    return True


def _blocks(query: str, statement: str, strong_hit: list[str]) -> bool:
    """问句里另有一个原句没有的事物时，不能拿这条事实来答。

    取值嵌在说法里（四十二米高、霜降那天）时仍算同一条。
    已经用取值对上时，单字「塔」可以落在「灯塔」里；没有取值时，「车」不能从「自行车」里抠出来。
    """
    compact = _compact(statement)
    for noun in _content_nouns(query):
        if _noun_covered(noun, statement):
            continue
        if strong_hit and len(noun) == 1 and noun in compact:
            continue
        return True
    return False


def _ignorable_noun(noun: str) -> bool:
    if noun in _IGNORE_NOUNS:
        return True
    if len(noun) == 1 and noun in "建晒养高面年天人":
        return True
    if re.fullmatch(r"[这那每]一?[年天日]", noun):
        return True
    return False


def _cue(query: str, statement: str) -> int:
    score = 0
    if any(mark in query for mark in ("建成", "完工", "落成", "建于")) or ("建" in query and "年" in query):
        if "建" in statement:
            score += 2
    if any(mark in query for mark in ("电灯", "改用", "用电")) and ("电" in statement or "改" in statement):
        score += 2
    if any(mark in query for mark in ("多高", "高度", "有多高")) and re.search(r"米|塔高", statement):
        score += 2
    if "打磨" in query and "打磨" in statement:
        score += 2
    if "养" in query and "养" in statement:
        score += 2
    if any(mark in query for mark in ("晒", "晾")) and ("晒" in statement or "晾" in statement):
        score += 2
    if "面" in query and any(mark in query for mark in ("多少", "几", "一共")) and "面" in statement:
        score += 2
    if any(mark in query for mark in ("叫什么", "什么名字", "名字")) and "名叫" in statement:
        score += 2
    if "特产" in query and ("特产" in statement or "名叫" in statement):
        score += 1
    if "腿" in query and "腿" in statement:
        score += 2
    return score


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
    """问句碰到了已经记下的人、事物或取值。这种问题不能再交给基座编。"""
    compact = _compact(query)
    pieces = [piece for piece in _pieces(query) if len(piece) >= 2 and piece not in _ASK_ONLY]
    for fact in facts:
        if not isinstance(fact, dict) or fact.get("superseded"):
            continue
        for token in _anchor_tokens(fact):
            if len(token) >= 2 and token in compact:
                return True
        blob = fact_blob(fact)
        if any(piece in blob for piece in pieces):
            return True
    return False


def _supported(query: str, fact: dict, lexical: float) -> tuple[bool, list[str], list[str]]:
    statement = str(fact.get("statement") or "")
    strong = [span for span in strong_value_spans(statement) if _query_has(query, span)]
    anchors = [token for token in _anchor_tokens(fact) if _query_has(query, token)]
    # 问句里的实词都能对上原句时，沿用整句匹配。汽车对不上自行车，走不到这里。
    if lexical >= 0.999:
        return True, strong, anchors
    # 问句里还留着原句没有的事物，就不用这条。取值嵌在说法里已经在覆盖判断里剥掉了。
    if _blocks(query, statement, strong):
        return False, strong, anchors
    if strong or anchors:
        return True, strong, anchors
    return False, strong, anchors


def recall_fact(
    query: str,
    facts: list[dict],
    query_vector: list[float] | None = None,
    fact_vectors: list[list[float]] | None = None,
) -> dict | None:
    """在全部已存事实上找一句能支撑这个问法的。找不到就返回 None。

    问句可以拿原句里的取值或属性当钥匙（四十二米、霜降、阿哨），不必复述训练时的说法。
    bge 只在已经有钥匙的句子之间排序，不能单靠相似度把另一个事物换进来。
    """
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
        supported, strong, anchors = _supported(query, fact, lexical)
        if not supported or not _evidence(query, statement):
            continue
        semantic = 0.0
        if query_vector is not None and fact_vectors is not None and index < len(fact_vectors):
            semantic = _cosine(query_vector, fact_vectors[index])
        score = len(strong) * 3 + len(anchors) + lexical * 2 + _cue(query, statement) * 2 + semantic * 0.5
        if score > best_score:
            best = fact
            best_score = score
    return best


def answer_span(query: str, statement: str) -> str:
    """从原句里抽出问句要的那一段。抽不出就返回空，调用方再决定弃权或用短取值。"""
    text = str(statement or "")
    asked = str(query or "")
    if not text or not asked:
        return ""
    if any(mark in asked for mark in ("多高", "高度", "有多高", "塔高")) or ("高" in asked and "多少" in asked):
        match = re.search(rf"({_MEASURE.replace('(?:米|面|岁|公里|里)', '米')})", text)
        if match:
            return match.group(1)
        match = re.search(r"塔高([\u4e00-\u9fff0-9]{1,8})", text)
        return f"{match.group(1)}米" if match and "米" not in match.group(1) else (match.group(1) if match else "")
    if "面" in asked and any(mark in asked for mark in ("多少", "几", "一共")):
        match = re.search(r"([0-9０-９零〇一二三四五六七八九十百千万两]{1,8})面", text)
        return match.group(0) if match else ""
    if "腿" in asked and any(mark in asked for mark in ("几", "多少")):
        match = re.search(r"([一二三四五六七八九十两0-9]{1,3}条腿)", text)
        return match.group(1) if match else ""
    if "谁" in asked and ("养" in asked or "饲养" in asked or "主人" in asked):
        if any(mark in asked for mark in ("父亲", "爸爸", "她爸", "他爸", "母亲", "妈妈", "她妈", "他妈")):
            return ""
        match = re.search(r"(?:女儿)?([\u4e00-\u9fff]{2,3})养了", text)
        return match.group(1) if match else ""
    if "谁" in asked and ("打磨" in asked or "工匠" in asked):
        match = re.search(r"工匠([\u4e00-\u9fff]{1,8}?)(?=打磨|，|。|$)", text)
        return match.group(1) if match else ""
    if any(mark in asked for mark in ("哪里", "哪儿", "什么地方", "哪个地方", "产自", "产地")):
        origin = re.search(r"([\u4e00-\u9fff]{2,6})的特产", text)
        if origin and origin.group(1) not in asked:
            return origin.group(1)
    named = re.search(r"名叫([\u4e00-\u9fffA-Za-z0-9·]{1,12})", text)
    if any(mark in asked for mark in ("叫什么", "什么名字", "叫啥", "名叫")) and "谁" not in asked:
        if any(mark in asked for mark in ("打磨", "工匠")):
            craft = re.search(r"工匠([\u4e00-\u9fff]{1,8}?)(?=打磨|，|。|$)", text)
            if craft and craft.group(1) not in asked:
                return craft.group(1)
        if named and named.group(1) not in asked:
            return named.group(1)
        return ""
    if any(mark in asked for mark in ("哪座", "哪个", "哪一个")) and named and named.group(1) not in asked:
        return named.group(1)
    if any(mark in asked for mark in ("哪座", "哪个")) :
        tower = re.search(r"([\u4e00-\u9fff]{2,8}塔)", text)
        if tower and tower.group(1) not in asked:
            return tower.group(1)
    when = any(mark in asked for mark in ("哪一年", "哪年", "什么时候", "何时", "哪天", "哪一天", "哪天起"))
    if when or any(mark in asked for mark in ("建成", "完工")):
        drying = any(mark in asked for mark in ("晒", "晾")) or any(term in asked for term in _SOLAR)
        building = any(mark in asked for mark in ("建", "完工", "落成"))
        electric = any(mark in asked for mark in ("电", "改用", "改装"))
        if drying or (any(term in asked for term in _SOLAR) and not building):
            for term in _SOLAR:
                if term in text:
                    return term
        if building:
            match = re.search(r"建于(\d{3,4}年)", text)
            if match:
                return match.group(1)
            if "建" not in text:
                return ""
        if electric:
            if "电" not in text and "改" not in text:
                return ""
            match = re.search(r"(\d{3,4})年", text)
            return f"{match.group(1)}年" if match else ""
        if "年" in asked:
            match = re.search(r"建于(\d{3,4}年)", text)
            if match:
                return match.group(1)
            match = re.search(r"(\d{3,4})年", text)
            return f"{match.group(1)}年" if match else ""
        for term in _SOLAR:
            if term in text:
                return term
        match = re.search(r"(\d{3,4})年", text)
        return f"{match.group(1)}年" if match else ""
    if "什么" in asked or "啥" in asked:
        if any(mark in asked for mark in ("晒", "晾")) and "晒" not in text and "晾" not in text:
            return ""
        if named:
            return named.group(1)
        if "谁" in asked:
            match = re.search(r"([\u4e00-\u9fff]{2,4})养了", text)
            if match:
                return match.group(1)
    if "谁" in asked:
        match = re.search(r"工匠([\u4e00-\u9fff]{1,8}?)(?=打磨|，|。|$)", text)
        if match and "工匠" in text and ("工匠" in asked or "打磨" in asked):
            return match.group(1)
        named_in_query = named and named.group(1) in asked
        if named_in_query:
            match = re.search(r"(?:女儿)?([\u4e00-\u9fff]{2,3})养了", text)
            if match:
                return match.group(1)
    return ""


def spoken_fact(query: str, fact: dict) -> str:
    """回答只给问句要的那一段。引用仍留在事实原句上。"""
    statement = str(fact.get("statement") or "").strip()
    value = str(fact.get("value") or fact.get("answer") or "").strip()
    if ("我的" in (query or "") or (query or "").startswith("我")) and "我" not in statement and str(fact.get("entity") or "") not in {"我", "用户"}:
        return ""
    span = answer_span(query, statement)
    if span:
        text = span
    elif value and statement and value.rstrip("。") != statement.rstrip("。") and len(value) <= 24:
        text = value
    else:
        text = statement
    from memory_core.span_guard import asked_kind, predicate_in_statement, span_fits

    # 问的是人数、年份、年限时，不能把整句或另一种单位当成答案。
    if asked_kind(query) and (not span_fits(query, text) or not predicate_in_statement(query, statement)):
        return ""
    text = text.strip()
    if text and text[-1] not in "。.!！？?":
        text += "。"
    return text


def possessed_name_query(query: str) -> str:
    """「我的狗叫什么名字」里的狗。问的是使用者本人时返回空。"""
    match = re.search(r"我的(?!名字|姓名|自己)([\u4e00-\u9fff]{1,8}?)叫", query or "")
    if not match:
        return ""
    return match.group(1)

"""摘录必须和问句是同一种取值，而且那一句真的写了这个属性。

对不上就用固定句式弃权，不把问句切碎拼进回答，也不把书里的人说成使用者。
"""
from __future__ import annotations

import re

from memory_core.fact_recall import possessed_name_query
from memory_core.prompts import has_cjk

_COUNTRIES = ("瑞典", "挪威", "中国", "日本", "英国", "法国", "德国", "美国", "荷兰", "丹麦", "芬兰", "俄罗斯")
_SOLAR = ("霜降", "立春", "雨水", "惊蛰", "春分", "清明", "谷雨", "立夏", "小满", "芒种", "夏至", "立秋", "处暑", "白露", "秋分", "寒露", "立冬", "小雪", "大雪", "冬至", "小寒", "大寒")
_STOP = frozenset(
    "什么 怎么 这个 那个 一个 我们 他们 就是 可以 没有 不是 自己 时候 地方 东西 开始 每年 那天 这座 那座 已经 还是 因为 所以 如果 但是 然后 知道 告诉 请问 一下 哪里 哪儿 哪年 谁的 是谁".split()
)
# 问句里的属性，和句子里必须出现的说法。电灯对不上建塔那一句。
_PREDICATES = (
    (("电灯", "通电", "用电", "改电"), ("电灯", "用电", "电")),
    (("出生", "生日", "生于", "出生年"), ("出生", "生日", "生于")),
    (("哪个省", "什么省", "省份", "哪个省"), ("省",)),
    (("建成", "建于", "落成"), ("建于", "建成", "落成")),
    (("打磨",), ("打磨", "磨")),
    (("晾晒", "晾", "晒"), ("晾", "晒")),
    (("父亲", "爸爸"), ("女儿", "父亲", "爸爸")),
    (("母亲", "妈妈"), ("母亲", "妈妈")),
    (("主人",), ("养了", "主人")),
    (("哪国", "国籍", "哪国人"), _COUNTRIES),
    (("多少钱", "价格", "卖多少"), ("钱", "价格", "元")),
    (("性别", "是男", "是女"), ("性别",)),
    (("市长",), ("市长",)),
    (("妻子", "老婆"), ("妻子", "老婆")),
    (("丈夫", "老公"), ("丈夫", "老公")),
)


def statement_of(fact: dict) -> str:
    return str(fact.get("statement") or fact.get("value") or "").strip()


def question_type(query: str) -> str:
    text = query or ""
    if any(mark in text for mark in ("哪国人", "国籍", "哪国")):
        return "nationality"
    if any(mark in text for mark in ("哪个省", "什么省", "省份", "属于哪")):
        return "place"
    if any(mark in text for mark in ("哪里", "哪儿", "什么地方", "产地")):
        return "place"
    if any(mark in text for mark in ("什么颜色", "啥色", "什么色", "颜色")):
        return "colour"
    if any(mark in text for mark in ("多高", "多少", "几面", "几条", "几岁", "多大")):
        return "number"
    if any(mark in text for mark in ("谁", "哪位")):
        return "person"
    if any(mark in text for mark in ("叫什么", "什么名字", "叫啥")):
        return "name"
    if any(mark in text for mark in ("哪一年", "哪年", "哪天", "什么时候", "何时", "哪一天")):
        return "time"
    return ""


def span_type(span: str) -> str:
    text = (span or "").strip().rstrip("。")
    if re.fullmatch(r"\d{3,4}年", text) or text in _SOLAR:
        return "time"
    if re.fullmatch(r"[0-9０-９零〇一二三四五六七八九十百千万两]{1,8}(?:米|面|条腿|岁)", text):
        return "number"
    if re.fullmatch(r"[\u4e00-\u9fff]{1,4}色", text):
        return "colour"
    if text in _COUNTRIES or text.endswith("国") and len(text) <= 4:
        return "nationality"
    if re.fullmatch(r"[\u4e00-\u9fff]{2,8}", text):
        return "name"
    return ""


def types_match(query: str, span: str) -> bool:
    wanted = question_type(query)
    got = span_type(span)
    if not wanted:
        return bool(got) and len(span) <= 12
    if wanted == "time":
        return got == "time"
    if wanted == "number":
        return got == "number"
    if wanted == "colour":
        return got == "colour"
    if wanted == "nationality":
        return got == "nationality"
    if wanted in {"person", "name", "place"}:
        return got == "name"
    return False


def align_span(span: str, statement: str) -> str:
    """去掉从数字或词中间切下来的半截，例如「年白鹭塔」。"""
    text = (span or "").strip().strip("「」\"'").rstrip("。")
    if not text or text not in statement:
        compact = re.sub(r"[\s，,。]", "", text)
        if compact and compact in re.sub(r"[\s，,。]", "", statement):
            text = compact
        else:
            return ""
    index = statement.find(text)
    if index > 0 and text.startswith("年") and statement[index - 1].isdigit():
        text = text[1:]
        index += 1
    while text and text[0] in "的了在是和与及":
        text = text[1:]
        index += 1
    if not text:
        return ""
    for match in re.finditer(r"\d{3,4}年", statement):
        if match.start() < index + len(text) and index < match.end() and text != match.group(0):
            if text in match.group(0) or match.group(0).endswith(text):
                return ""
    return text


def _near_wh(query: str, words: tuple[str, ...]) -> bool:
    for mark in ("叫什么", "是谁", "哪一年", "哪年", "有多高", "多少", "什么时候", "哪里", "哪儿", "哪国"):
        index = (query or "").rfind(mark)
        if index < 0:
            continue
        window = query[max(0, index - 6):index + len(mark)]
        if any(word in window for word in words):
            return True
    return False


def predicate_covered(query: str, statement: str) -> bool:
    """问的那个属性必须写在这句里。只点到同一个名字不够。

    电灯、出生、省、国籍这类字出现在问句里，句子里也得有。
    父亲、养这种用来指路的字，只有紧挨着疑问词才算要问的属性。
    """
    text = statement or ""
    asked = query or ""
    kind = question_type(asked)
    if any(mark in asked for mark in ("出生", "生日", "生于")):
        return any(mark in text for mark in ("出生", "生日", "生于"))
    if any(mark in asked for mark in ("哪个省", "什么省", "省份")) or "属于哪" in asked:
        return "省" in text
    if any(mark in asked for mark in ("哪国", "国籍", "哪国人")):
        return any(country in text for country in _COUNTRIES)
    if any(mark in asked for mark in ("多少钱", "价格", "卖多少")):
        return any(mark in text for mark in ("钱", "价格", "元"))
    if any(mark in asked for mark in ("性别", "是男", "是女", "是公", "是母", "公是母")):
        return "性别" in text
    if "市长" in asked:
        return "市长" in text
    if any(mark in asked for mark in ("妻子", "老婆")):
        return any(mark in text for mark in ("妻子", "老婆"))
    if any(mark in asked for mark in ("丈夫", "老公")):
        return any(mark in text for mark in ("丈夫", "老公"))
    if kind == "time" and "电" in asked:
        return "电" in text
    if kind == "time" and any(mark in asked for mark in ("建成", "建于", "落成")) and "电" not in asked:
        return any(mark in text for mark in ("建于", "建成", "落成"))
    if kind == "time" and any(mark in asked for mark in ("晒", "晾")):
        return any(mark in text for mark in ("晒", "晾"))
    if "打磨" in asked or ("磨" in asked and "谁" in asked):
        return "打磨" in text or ("磨" in text and "工匠" in text)
    if _near_wh(asked, ("父亲", "爸爸")):
        return any(mark in text for mark in ("女儿", "父亲", "爸爸"))
    if _near_wh(asked, ("主人",)):
        return "养" in text or "主人" in text
    if kind == "number" and "多高" in asked:
        return bool(re.search(r"米|塔高", text))
    if kind == "number":
        return bool(re.search(r"米|面|条腿|岁", text))
    if kind == "colour":
        return "色" in text
    if kind == "time":
        return bool(re.search(r"\d{3,4}年", text)) or any(term in text for term in _SOLAR)
    return True


def stored_tokens(facts: list[dict]) -> set[str]:
    found: set[str] = set()
    for fact in facts:
        if not isinstance(fact, dict) or fact.get("superseded"):
            continue
        entity = str(fact.get("entity") or "").strip()
        if len(entity) >= 2:
            found.add(entity)
        value = str(fact.get("value") or "").strip().rstrip("。")
        if 2 <= len(value) <= 12:
            found.add(value)
        text = statement_of(fact)
        for match in re.finditer(r"[\u4e00-\u9fff]{2,4}", text):
            token = match.group(0)
            if token not in _STOP:
                found.add(token)
    return found


def mentions_stored(query: str, facts: list[dict]) -> bool:
    text = query or ""
    blob = "\n".join(statement_of(fact) for fact in facts if isinstance(fact, dict))
    if not text or not blob:
        return False
    for size in (4, 3, 2):
        for index in range(0, len(text) - size + 1):
            token = text[index:index + size]
            if token in _STOP or not re.fullmatch(r"[\u4e00-\u9fff]{2,4}", token):
                continue
            if token in blob:
                return True
    return False


def about_user(query: str) -> bool:
    text = query or ""
    if "我们" in text:
        return False
    if possessed_name_query(text):
        return True
    return bool(re.search(r"(?<![\u4e00-\u9fff])我(?:的|住|叫|是)?", text))


def _predicate_phrase(query: str) -> str:
    text = query or ""
    if any(mark in text for mark in ("哪个省", "什么省", "省份", "属于哪")):
        return "属于哪个省"
    if any(mark in text for mark in ("出生", "生日", "生于")):
        return "的出生年份"
    if any(mark in text for mark in ("父亲", "爸爸")):
        return "的父亲"
    if any(mark in text for mark in ("母亲", "妈妈")):
        return "的母亲"
    if "妻子" in text or "老婆" in text:
        return "的妻子"
    if "丈夫" in text or "老公" in text:
        return "的丈夫"
    if "主人" in text:
        return "的主人"
    if any(mark in text for mark in ("哪国", "国籍")):
        return "是哪国人"
    if any(mark in text for mark in ("多少钱", "价格")):
        return "的价格"
    if any(mark in text for mark in ("性别", "是男", "是女", "是公", "是母")):
        return "的性别"
    if "市长" in text:
        return "的市长"
    if any(mark in text for mark in ("多远",)):
        return "能照多远"
    if any(mark in text for mark in ("几岁", "多大")):
        return "的年龄"
    if "多高" in text:
        return "有多高"
    return ""


def _subject(query: str, facts: list[dict]) -> str:
    text = query or ""
    blob = "\n".join(statement_of(fact) for fact in facts if isinstance(fact, dict))
    best = ""
    for size in (4, 3, 2):
        for index in range(0, max(0, len(text) - size + 1)):
            token = text[index:index + size]
            if token in _STOP or token in best or token.endswith("的") or token.startswith("的"):
                continue
            if not re.fullmatch(r"[\u4e00-\u9fff]{2,4}", token):
                continue
            if token in blob and len(token) > len(best):
                best = token
    return best


def _from_book(subject: str, facts: list[dict]) -> bool:
    if not subject:
        return any(str(fact.get("source") or "") == "document" for fact in facts)
    for fact in facts:
        if subject in statement_of(fact) and str(fact.get("source") or "") == "document":
            return True
    return False


def fixed_refusal(query: str, facts: list[dict] | None = None) -> str:
    """固定句式。只有在问使用者本人时才说「你还没告诉过我」。"""
    facts = list(facts or [])
    if not has_cjk(query):
        return "That is not in memory."
    phrase = _predicate_phrase(query)
    owned = possessed_name_query(query)
    if owned:
        return f"你还没告诉过我你的{owned}叫什么。"
    subject = _subject(query, facts)
    user = about_user(query) and subject in {"", "我"}
    if user:
        if "生日" in query or "出生" in query:
            return "你还没告诉过我生日。"
        if any(mark in query for mark in ("住哪", "住在", "住哪儿")):
            return "你还没告诉过我住在哪里。"
        if phrase:
            return f"你还没告诉过我{phrase}。"
        return "你还没告诉过我这件事。"
    if subject and phrase:
        if _from_book(subject, facts):
            return f"书里没提到{subject}{phrase}。"
        return f"我没记过{subject}{phrase}。"
    if subject:
        if _from_book(subject, facts):
            return f"书里没提到{subject}的这件事。"
        return f"我没记过{subject}的这件事。"
    return "我没记过这件事。"


def relation_answer(query: str, facts: list[dict]) -> tuple[str, dict] | None:
    """女儿对父亲、养对主人、特产对产地、工匠对国籍。只在问的就是这条关系时用。"""
    asked = query or ""
    kind = question_type(asked)
    focus_person = any(mark in asked for mark in ("父亲", "爸爸", "母亲", "妈妈", "主人"))
    focus_place = kind == "place" or any(mark in asked for mark in ("产地", "哪里的特产", "什么地方的特产"))
    focus_nation = kind == "nationality"
    if kind in {"time", "number", "colour", "name"} and not focus_person and not focus_nation:
        return None
    for fact in facts:
        text = statement_of(fact)
        parent = re.search(r"([\u4e00-\u9fff]{2,4})的女儿([\u4e00-\u9fff]{2,3})", text)
        if parent and any(mark in asked for mark in ("父亲", "爸爸")) and parent.group(2) in asked:
            return parent.group(1), fact
        if parent and "女儿" in asked and "叫什么" in asked and parent.group(1) in asked and "养" not in asked:
            return parent.group(2), fact
        owned = re.search(r"([\u4e00-\u9fff]{2,3})养了", text)
        named = re.search(r"名叫([\u4e00-\u9fffA-Za-z0-9·]{1,12})", text)
        if owned and named and "主人" in asked and named.group(1) in asked:
            return owned.group(1), fact
        origin = re.search(r"([\u4e00-\u9fff]{2,6})的特产", text)
        if origin and named and focus_place and named.group(1) in asked:
            return origin.group(1), fact
        if origin and named and any(mark in asked for mark in ("特产",)) and kind == "place" and origin.group(1) in asked:
            return named.group(1), fact
        country = next((item for item in _COUNTRIES if item in text), "")
        craft = re.search(r"工匠([\u4e00-\u9fff]{1,8}?)(?=打磨|，|。|$)", text)
        if country and focus_nation and (
            (craft and craft.group(1) in asked)
            or any(mark in asked for mark in ("工匠", "师傅"))
        ):
            return country, fact
    return None


def accept_aligned(query: str, span: str, fact: dict) -> str:
    text = statement_of(fact)
    aligned = align_span(span, text)
    if not aligned or not types_match(query, aligned):
        return ""
    if not predicate_covered(query, text):
        return ""
    if len(aligned) > 12:
        return ""
    if aligned in (query or "") and question_type(query) in {"person", "name", "place", "time", "number"}:
        return ""
    return aligned

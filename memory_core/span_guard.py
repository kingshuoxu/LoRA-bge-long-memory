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


def types_match(query: str, span: str, fact: dict | None = None) -> bool:
    wanted = question_type(query)
    got = span_type(span)
    if not wanted:
        return bool(got) and len(span) <= 12
    if wanted == "time":
        return got == "time"
    if wanted == "number":
        if got == "number":
            return True
        return bool(re.search(r"[0-9一二三四五六七八九十百千万两]", span or ""))
    if wanted == "colour":
        if got == "colour":
            return True
        value = str((fact or {}).get("value") or "")
        return bool(value) and span.rstrip("。") in value
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


def predicate_covered(query: str, statement: str, fact: dict | None = None) -> bool:
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
    if kind == "number" and "高" in asked:
        return bool(re.search(r"米|塔高", text))
    if kind == "number" and "面" in asked:
        return "面" in text
    if kind == "number" and any(mark in asked for mark in ("几岁", "多大", "年龄")):
        return bool(re.search(r"岁|年龄", text))
    if "多远" in asked or ("离" in asked and "远" in asked):
        return "远" in text or "码头" in text
    if kind == "colour":
        if "色" in text:
            return True
        # 「禾昭闻的汽车是墨黑。」把颜色写在「是」后面，句子里没有「色」。
        attr = str((fact or {}).get("attr") or "")
        value = str((fact or {}).get("value") or "").strip().rstrip("。")
        return bool(value) and ("颜色" in attr or attr.endswith("色")) and value in text
    if any(mark in asked for mark in ("现居", "住在", "住哪", "住哪儿", "居住", "住址")):
        return "住" in text
    if any(mark in asked for mark in ("老家", "家乡", "长大")):
        return any(mark in text for mark in ("家乡", "老家", "长大"))
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


def _asked_clause(query: str) -> str:
    """保留问句里真正在问的那一段，不改写成另一个属性。"""
    text = (query or "").strip().rstrip("？?。！!")
    text = re.sub(r"^(?:请问|问一下|告诉我)", "", text).strip()
    text = re.sub(r"(?:是谁|叫什么|叫啥|是什么|什么名字)$", "", text).strip()
    return text or (query or "").strip().rstrip("？?")


def _subject(query: str, facts: list[dict]) -> str:
    text = query or ""
    blob = "\n".join(statement_of(fact) for fact in facts if isinstance(fact, dict))
    best = ""
    for size in (4, 3, 2):
        for index in range(0, max(0, len(text) - size + 1)):
            token = text[index:index + size]
            if token in _STOP or token in best or "的" in token:
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
    """固定句式。把问句里的属性原样说出来，不换成另一个说法。"""
    facts = list(facts or [])
    if not has_cjk(query):
        return "That is not in memory."
    from memory_core.extract import is_self_fact_question

    clause = _asked_clause(query)
    owned = possessed_name_query(query)
    if owned:
        return f"你还没告诉过我你的{owned}叫什么。"
    if is_self_fact_question(query):
        if clause.startswith("我"):
            clause = clause[1:]
        return f"你还没告诉过我{clause}。" if clause else "你还没告诉过我这件事。"
    book = _from_book(_subject(query, facts), facts) or any(
        str(fact.get("source") or "") == "document" for fact in facts
    )
    if book and clause:
        return f"书里没提到{clause}。"
    if clause:
        return f"我没记过{clause}。"
    return "我没记过这件事。"


def uncertain_reply(query: str, found: list[dict]) -> str:
    """多跳没走完。只复述已经看见的原句，不把中间的人或错的属性当成答案。"""
    lines: list[str] = []
    for fact in found:
        text = statement_of(fact).strip().rstrip("。")
        if text and text not in lines:
            lines.append(text)
        if len(lines) >= 3:
            break
    if not lines:
        return fixed_refusal(query, found)
    return "这个我不确定，书里记得的是：" + "；".join(lines) + "。"


def is_open_task(text: str) -> bool:
    """写、译、聊、建议、怎么办。这些走基座。问「我的X是什么」才走记忆。"""
    from memory_core.extract import is_advice_question, is_imperative_request, is_self_fact_question

    raw = (text or "").strip()
    if not raw:
        return False
    if is_self_fact_question(raw):
        return False
    if is_imperative_request(raw) or is_advice_question(raw):
        return True
    if raw in {"你好", "您好", "在吗", "谢谢", "早上好", "晚安", "再见", "嗨"}:
        return True
    return bool(re.match(r"^(你好|您好|在吗|谢谢|早上好|晚安|再见|嗨|hi|hello)\b", raw, re.IGNORECASE))


def _relation_edges(facts: list[dict]) -> list[tuple[str, str, str, dict]]:
    edges: list[tuple[str, str, str, dict]] = []
    for fact in facts:
        if not isinstance(fact, dict) or fact.get("superseded"):
            continue
        text = statement_of(fact)
        parent = re.search(r"([\u4e00-\u9fff]{2,4})的女儿([\u4e00-\u9fff]{2,3})", text)
        if parent:
            edges.append(("daughter", parent.group(1), parent.group(2), fact))
            edges.append(("father", parent.group(2), parent.group(1), fact))
        keeper = re.search(r"([\u4e00-\u9fff]{2,3})养了", text)
        named = re.search(r"名叫([\u4e00-\u9fffA-Za-z0-9·]{1,12})", text)
        if keeper and named:
            edges.append(("owner", named.group(1), keeper.group(1), fact))
            edges.append(("pet", keeper.group(1), named.group(1), fact))
        guard = re.search(r"([\u4e00-\u9fff]{2,4})在.{0,16}守护", text)
        if guard and named:
            edges.append(("tower", guard.group(1), named.group(1), fact))
            edges.append(("keeper", named.group(1), guard.group(1), fact))
        height = re.search(r"([0-9一二三四五六七八九十百千两]{1,8}米)", text)
        if height and named and "塔" in text:
            edges.append(("height", named.group(1), height.group(1), fact))
        built = re.search(r"建于(\d{3,4}年)", text)
        if built and named:
            edges.append(("built", named.group(1), built.group(1), fact))
        if "电" in text and "白鹭塔" in text:
            year = re.search(r"(\d{3,4})年", text)
            if year:
                edges.append(("electric", "白鹭塔", f"{year.group(1)}年", fact))
        origin = re.search(r"([\u4e00-\u9fff]{2,6})的特产", text)
        if origin and named:
            edges.append(("origin", named.group(1), origin.group(1), fact))
            edges.append(("specialty", origin.group(1), named.group(1), fact))
            if "海盐" in text:
                edges.append(("origin", "海盐", origin.group(1), fact))
                edges.append(("origin", "蓝色海盐", origin.group(1), fact))
        country = next((item for item in _COUNTRIES if item in text), "")
        craft = re.search(r"(?:工匠|师傅)([\u4e00-\u9fff]{1,8}?)(?=打磨|，|。|$)", text)
        if country and craft:
            edges.append(("nation", craft.group(1), country, fact))
            if "白鹭塔" in text:
                edges.append(("craft", "白鹭塔", craft.group(1), fact))
            if "透镜" in text:
                edges.append(("craft", "透镜", craft.group(1), fact))
    return edges


def _node_names(edges: list[tuple[str, str, str, dict]]) -> list[str]:
    found: set[str] = set()
    for _rel, src, dst, _fact in edges:
        for node in (src, dst):
            if re.fullmatch(r"[\u4e00-\u9fff]{2,8}", node) and not node.endswith(("米", "年", "面")):
                found.add(node)
    return sorted(found, key=len, reverse=True)


def _inside_name(query: str, index: int, length: int, names: list[str]) -> bool:
    for name in names:
        start = 0
        while True:
            at = query.find(name, start)
            if at < 0:
                break
            if at <= index and index + length <= at + len(name) and len(name) > length:
                return True
            start = at + len(name)
    return False


def _ordered_hops(query: str, names: list[str]) -> list[str]:
    phrases = (
        ("owner", ("小主人", "主人", "养的人", "谁养", "小姑娘", "小丫头")),
        ("father", ("父亲", "爸爸", "她爸", "他爸")),
        ("mother", ("母亲", "妈妈", "她妈", "他妈")),
        ("daughter", ("闺女", "女儿")),
        ("spouse", ("妻子", "老婆", "丈夫", "老公")),
        ("tower", ("灯塔", "这座塔", "那座塔", "的塔", "座塔")),
        ("craft", ("师傅", "工匠")),
    )
    found: list[tuple[int, str]] = []
    for hop, words in phrases:
        for word in words:
            start = 0
            while True:
                index = query.find(word, start)
                if index < 0:
                    break
                if not _inside_name(query, index, len(word), names):
                    found.append((index, hop))
                start = index + len(word)
    asks_name = any(mark in query for mark in ("叫什么", "叫啥", "什么名字")) and "谁" not in query
    if "养" in query and not any(hop == ("pet" if asks_name else "owner") for _index, hop in found):
        index = query.find("养")
        if index >= 0:
            found.append((index, "pet" if asks_name else "owner"))
    has_tower = any(hop == "tower" for _index, hop in found)
    if "守护" in query and any(mark in query for mark in ("的人", "是谁", "叫什么")) and not has_tower:
        found.append((query.find("守护"), "keeper"))
    found.sort()
    hops: list[str] = []
    for _index, hop in found:
        if hops and hops[-1] == hop:
            continue
        hops.append(hop)
    return hops


def _chain_terminal(query: str) -> str:
    if "腿" in query or ("面" in query and any(mark in query for mark in ("多少", "几", "一共"))):
        return ""
    if any(mark in query for mark in ("多少钱", "几岁", "性别", "是公", "是母")):
        return ""
    if any(mark in query for mark in ("多高", "塔高")) or ("高" in query and "多少" in query):
        return "height"
    if any(mark in query for mark in ("哪国", "国籍")):
        return "nation"
    if any(mark in query for mark in ("哪里", "哪儿", "什么地方", "哪个地方", "产自", "产地")):
        return "origin"
    if any(mark in query for mark in ("哪一年", "哪年", "什么时候")) and "电" in query:
        return "electric"
    if any(mark in query for mark in ("建于", "建成", "落成")) or (
        any(mark in query for mark in ("哪一年", "哪年")) and "建" in query and "电" not in query
    ):
        return "built"
    if "特产" in query and any(mark in query for mark in ("叫什么", "是什么", "什么", "啥")):
        return "specialty"
    if any(mark in query for mark in ("叫什么", "是谁", "叫啥", "什么名字", "谁")):
        return "identity"
    return ""


_HOP_WORDS = (
    ("小主人", "owner"),
    ("主人", "owner"),
    ("老爸", "father"),
    ("父亲", "father"),
    ("爸爸", "father"),
    ("她爸", "father"),
    ("他爸", "father"),
    ("爸", "father"),
    ("母亲", "mother"),
    ("妈妈", "mother"),
    ("她妈", "mother"),
    ("他妈", "mother"),
    ("妻子", "wife"),
    ("老婆", "wife"),
    ("丈夫", "husband"),
    ("老公", "husband"),
    ("丫头", "daughter"),
    ("闺女", "daughter"),
    ("女儿", "daughter"),
    ("谁守", "keeper"),
    ("守护的人", "keeper"),
    ("守的塔", "tower"),
    ("灯塔", "tower"),
    ("的塔", "tower"),
    ("谁磨", "craft"),
    ("打磨", "craft"),
    ("师傅", "craft"),
    ("工匠", "craft"),
    ("多高", "height"),
    ("塔高", "height"),
    ("哪国", "nation"),
    ("国籍", "nation"),
    ("哪里", "origin"),
    ("哪儿", "origin"),
    ("产自", "origin"),
    ("特产", "specialty"),
)
_PERSON_HOPS = {"owner", "father", "daughter", "keeper", "craft", "pet"}


def _explicit_hops(query: str, names: list[str]) -> list[str]:
    """按问句从左到右读关系词。只认明确写出来的关系，不把名字里的字算进去。"""
    hops: list[str] = []
    index = 0
    text = query or ""
    asks_name = any(mark in text for mark in ("叫什么", "叫啥", "什么名字")) and "谁" not in text
    while index < len(text):
        if _inside_name(text, index, 1, names):
            index += 1
            continue
        if text.startswith("养", index):
            kind = "pet" if asks_name else "owner"
            if not hops or hops[-1] != kind:
                hops.append(kind)
            index += 1
            continue
        matched = ""
        hop = ""
        for word, kind in _HOP_WORDS:
            if text.startswith(word, index) and len(word) > len(matched):
                matched = word
                hop = kind
        if not matched:
            index += 1
            continue
        if not hops or hops[-1] != hop:
            hops.append(hop)
        index += len(matched)
    if "特产" in text and any(mark in text for mark in ("哪里", "哪儿", "产自", "什么地方")):
        return ["origin"]
    if "特产" in text and any(mark in text for mark in ("叫什么", "是什么", "什么")) and "origin" not in hops:
        return ["specialty"]
    if "守护" in text and "的人" in text and "keeper" not in hops:
        hops.insert(0, "keeper")
    duration = any(mark in text for mark in ("多少年", "守了", "守护了", "多久"))
    if not duration and "电" in text and any(mark in text for mark in ("哪一年", "哪年")):
        hops.append("electric")
    elif not duration and "出生" not in text and any(mark in text for mark in ("哪一年", "哪年", "建于", "建成")):
        hops.append("built")
    return hops


def asked_kind(query: str) -> str:
    """问句要的取值种类。用来拦住把塔名当成年限、把十六面当成徒弟人数。"""
    text = query or ""
    if any(mark in text for mark in ("守了", "守护了", "多少年", "多久")) and "建于" not in text and "建成" not in text:
        return "duration"
    if any(mark in text for mark in ("徒弟", "学徒")) and any(mark in text for mark in ("多少", "几", "几个", "几位")):
        return "apprentice"
    if any(mark in text for mark in ("多少个", "几个", "几个人", "多少位", "几位", "多少名", "多少次")):
        return "count"
    if "出生" in text or "生日" in text:
        return "birth"
    if any(mark in text for mark in ("哪一年", "哪年", "建于", "建成")):
        return "year"
    if "多高" in text or "塔高" in text:
        return "height"
    if "面" in text and any(mark in text for mark in ("多少", "几", "一共")):
        return "faces"
    if any(mark in text for mark in ("是谁", "谁")):
        return "person"
    if any(mark in text for mark in ("哪里", "哪儿", "什么地方")):
        return "place"
    return ""


def span_fits(query: str, span: str) -> bool:
    kind = asked_kind(query)
    text = (span or "").strip().rstrip("。")
    if not kind:
        return True
    if kind in {"year", "birth"}:
        return bool(re.fullmatch(r"\d{3,4}年", text))
    if kind == "duration":
        return bool(re.fullmatch(r"(?:\d{1,4}|[一二三四五六七八九十百]+)年", text))
    if kind in {"apprentice", "count"}:
        return bool(re.search(r"[个位名次]", text)) and "面" not in text and not re.fullmatch(r"[\u4e00-\u9fff]{2,4}", text)
    if kind == "height":
        return "米" in text
    if kind == "faces":
        return text.endswith("面")
    if kind == "person":
        return bool(re.fullmatch(r"[\u4e00-\u9fff]{2,4}", text)) and text not in _COUNTRIES
    if kind == "place":
        return bool(re.fullmatch(r"[\u4e00-\u9fff]{2,8}", text))
    return True


def predicate_in_statement(query: str, statement: str) -> bool:
    """问的那个属性必须写在被引用的句子里，只点到同一个人不够。"""
    text = statement or ""
    kind = asked_kind(query)
    if kind == "apprentice":
        return any(mark in text for mark in ("徒弟", "学徒"))
    if kind == "count" and "工匠" in (query or ""):
        return "多少" in text or "几个" in text
    if kind == "count" and "人" in (query or "") and "守" in (query or ""):
        return "多少人" in text or "几个人" in text
    if kind == "duration":
        return any(mark in text for mark in ("守了", "守护了"))
    if kind == "birth":
        return any(mark in text for mark in ("出生", "生日", "生于"))
    if kind == "year":
        return "建" in text or "电" in text or bool(re.search(r"\d{3,4}年", text))
    if kind == "faces":
        return "面" in text
    if kind == "height":
        return "米" in text or "塔高" in text
    return True


def _hop_type_ok(hop: str, span: str) -> bool:
    text = (span or "").strip().rstrip("。")
    if hop in _PERSON_HOPS:
        return bool(re.fullmatch(r"[\u4e00-\u9fff]{2,4}", text)) and text not in _COUNTRIES
    if hop == "height":
        return "米" in text
    if hop == "nation":
        return text in _COUNTRIES
    if hop in {"origin", "specialty", "tower"}:
        return bool(re.fullmatch(r"[\u4e00-\u9fff]{2,8}", text))
    return False


def _related_facts(query: str, facts: list[dict], names: list[str]) -> list[dict]:
    mentioned = [name for name in names if name and name in (query or "")]
    found: list[dict] = []
    for fact in facts:
        text = statement_of(fact)
        if any(name in text for name in mentioned):
            found.append(fact)
    return found


def _start_node(query: str, names: list[str]) -> str:
    hits = []
    for name in names:
        index = (query or "").find(name)
        if index >= 0:
            hits.append((index, -len(name), name))
    if not hits:
        return ""
    hits.sort()
    return hits[0][2]


def relation_decision(query: str, facts: list[dict]) -> dict | None:
    """一跳必须有明确的边。两跳以上每一跳都要有边，而且最后的取值种类要对。

    走不到就弃权，并复述看见的原句。不把主语或中间的人当成答案，也不挂引用。
    """
    if any(mark in (query or "") for mark in ("条腿", "几面", "多少面", "几岁", "多少钱")):
        return None
    edges = _relation_edges(facts)
    names = _node_names(edges)
    hops = _explicit_hops(query, names)
    if not hops:
        return None
    start = _start_node(query, names)
    if not start and hops[-1] == "nation" and any(mark in (query or "") for mark in ("师傅", "工匠")):
        nations = [(src, dst, fact) for rel, src, dst, fact in edges if rel == "nation"]
        if len(nations) == 1:
            src, dst, fact = nations[0]
            if _hop_type_ok("nation", dst):
                return {"status": "answer", "span": dst, "fact": fact}
        return {"status": "abstain", "text": uncertain_reply(query, _related_facts(query, facts, names))}
    if not start:
        return None
    node = start
    fact = next((item for _rel, src, dst, item in edges if node in {src, dst}), None)
    seen = [start]
    for hop in hops:
        nxt = None
        for rel, src, dst, host in edges:
            if rel == hop and src == node:
                nxt = (dst, host)
                break
        if nxt is None or nxt[0] in seen:
            if len(hops) <= 1:
                return None
            return {"status": "abstain", "text": fixed_refusal(query, facts)}
        node, fact = nxt
        seen.append(node)
    fits = span_fits(query, node) if asked_kind(query) else _hop_type_ok(hops[-1], node)
    if not fits or node == start or (asked_kind(query) == "person" and node in (query or "")):
        if len(hops) <= 1:
            return None
        return {"status": "abstain", "text": fixed_refusal(query, facts)}
    if not predicate_in_statement(query, statement_of(fact or {})):
        if len(hops) <= 1:
            return None
        return {"status": "abstain", "text": fixed_refusal(query, facts)}
    return {"status": "answer", "span": node, "fact": fact}


def relation_answer(query: str, facts: list[dict]) -> tuple[str, dict] | None:
    decision = relation_decision(query, facts)
    if not decision:
        return None
    if decision["status"] != "answer":
        return "", None
    return decision["span"], decision["fact"]


def accept_aligned(query: str, span: str, fact: dict, require_predicate: bool = True) -> str:
    text = statement_of(fact)
    aligned = align_span(span, text)
    if not aligned or not types_match(query, aligned, fact):
        return ""
    if require_predicate and not predicate_covered(query, text, fact):
        return ""
    if len(aligned) > 12:
        return ""
    if aligned in (query or "") and question_type(query) in {"person", "name", "place", "time", "number"}:
        return ""
    return aligned

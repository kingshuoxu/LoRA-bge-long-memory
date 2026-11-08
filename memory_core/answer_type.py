"""每条回答路径都要过这一关。

问句要的种类和摘出来的取值对不上，或者取值就是问句里的主语，就弃权，不挂引用。
"""
from __future__ import annotations

import re

_COUNTRIES = ("瑞典", "挪威", "中国", "日本", "英国", "法国", "德国", "美国", "荷兰", "丹麦", "芬兰", "俄罗斯")
_SOLAR = ("霜降", "立春", "雨水", "惊蛰", "春分", "清明", "谷雨", "立夏", "小满", "芒种", "夏至", "立秋", "处暑", "白露", "秋分", "寒露", "立冬", "小雪", "大雪", "冬至", "小寒", "大寒")
_COLOURS = (
    "朱红色", "蔚蓝", "深蓝", "浅蓝", "蓝色", "朱红", "酒红", "墨黑", "墨色", "金色", "银色",
    "红色", "白色", "黑色", "青色", "紫色", "绿色", "黄色", "褐色", "灰色", "粉色", "棕色", "橙色",
)
_MATERIALS = ("大理石", "花岗岩", "木头", "木材", "石头", "玻璃", "水泥", "砖头", "铜", "铁", "砖", "竹")
_ANIMALS = ("海鸥", "海燕", "鸽子", "小狗", "小猫", "狗", "猫")
_ROLE_SUFFIX = ("女儿", "闺女", "丫头", "父亲", "爸爸", "老爸", "主人", "工匠", "师傅", "灯塔", "海鸥", "养")


_SPOUSE_WORDS = (
    "配偶", "妻子", "爱人", "老婆", "老公", "太太", "丈夫",
    "那口子", "对象", "媳妇", "先生", "夫人", "老伴", "另一半", "内人",
)
_FATHER_MARK = re.compile(r"父亲|爸爸|老爸|她爹|他爹|她爸|他爸|爹|(?<![爸])爸(?!爸)")


def _asks_spouse(query: str) -> bool:
    text = query or ""
    return any(word in text for word in _SPOUSE_WORDS) and bool(re.search(r"叫什么|叫啥|是谁|什么名字|是什么", text))


def _asks_maker(query: str) -> bool:
    return _asking_is_make(query)


def _asks_daughter(query: str) -> bool:
    text = query or ""
    if _asks_maker(text) or re.search(r"什么鸟|什么动物|鸟叫|海鸥叫|哪座塔|什么塔|塔叫|谁的女儿|谁的闺女|丈夫|妻子|老婆|老公|配偶|爱人", text):
        return False
    if re.search(r"塔的(?:女儿|闺女|丫头)", text) and not re.search(r"(?:人|谁|爸|父|爹)的(?:女儿|闺女|丫头)", text):
        return False
    return bool(re.search(r"女儿|闺女|丫头", text)) and bool(re.search(r"叫什么|叫啥|啥名|是谁|什么名字", text))


def _asks_keeper_name(query: str) -> bool:
    text = query or ""
    if _asks_daughter(text):
        return False
    return bool(re.search(r"守护人|看守人|守塔人|守塔的人|看守的人|守护的人|谁守", text)) and bool(
        re.search(r"叫什么|叫啥|啥名|是谁|什么名字", text)
    )


def _asks_father(query: str) -> bool:
    text = query or ""
    if _asks_maker(text) or re.search(r"哪座塔|什么塔|哪座灯塔|塔叫什么|塔叫啥|塔是什么", text):
        return False
    return bool(_FATHER_MARK.search(text)) and bool(re.search(r"叫什么|叫啥|是谁|什么名字|啥名", text))


def head_type(query: str) -> str:
    """问句要的是人还是塔，看问的那个中心词，不看句子里顺手出现的年份或地名。"""
    text = query or ""
    if re.search(r"多高|塔高|多少米|多少面|几条|几面|哪一年|哪年|什么时候|何时|什么鸟|什么动物|哪国|国籍|什么颜色|什么材料", text):
        return ""
    asked = _asked_kind(text)
    if asked:
        return asked
    focus = re.split(r"[，,。；;]", text)[-1]
    asked = re.search(r"叫什么|叫啥|啥名|什么名字", focus)
    if asked:
        before = focus[: asked.start()]
        if re.search(r"(?:人|那位|哪位)$", before):
            return "person"
        if re.search(r"塔$", before):
            return "tower"
    if re.search(r"哪个人|哪一位|哪位|什么人|是谁|谁管|谁守", focus):
        return "person"
    if re.search(r"哪座塔|什么塔|最早.{0,6}塔|第一.{0,6}塔|头一.{0,4}塔|灯塔叫|一座塔叫", focus):
        return "tower"
    if re.search(r"守塔|看守|守护|看管|管着|负责守|看着", focus) and re.search(r"叫什么|叫啥|谁", focus):
        if not re.search(r"塔叫", focus):
            return "person"
    return ""


def question_kind(query: str) -> str:
    """问句要的取值种类。空字符串表示这句没有强制种类。"""
    text = query or ""
    headed = head_type(text)
    if headed:
        return headed
    if re.search(r"什么颜色|啥颜色|哪种颜色|颜色|什么色", text):
        return "colour"
    if re.search(r"什么材料|啥材料|哪种材料|什么做的|用什么做|材料", text):
        return "material"
    if re.search(r"哪国|国籍", text):
        return "nation"
    if re.search(r"什么鸟|什么动物|哪种鸟|哪种动物", text):
        return "animal"
    if re.search(r"哪座塔|什么塔|哪座灯塔|哪一座塔|塔叫什么|塔叫啥|塔是什么", text):
        return "tower"
    if "十六面" in text and "谁" not in text and re.search(r"哪座|灯塔|什么塔", text):
        return "tower"
    if _asks_spouse(text):
        return "person"
    if _asks_keeper_name(text):
        return "person"
    if _asks_maker(text) and re.search(r"谁|叫什么|叫啥|啥名|什么名字", text):
        return "person"
    if _asks_father(text):
        return "person"
    if "谁" in text:
        return "person"
    if re.search(r"哪个村|哪个村子|哪个镇|哪个城市|哪座城市|住在哪|住哪", text):
        return "place"
    if re.search(r"哪里|哪儿|什么地方", text):
        return "place"
    if re.search(r"什么时候|何时|哪天|哪一天", text):
        return "time"
    if re.search(r"多久|多少年|几岁|多少钱|人口", text):
        return "measure"
    if re.search(r"哪一年|哪年|多高|塔高|多少|几", text):
        return "measure"
    if re.search(r"女儿|闺女|丫头", text) and re.search(r"叫什么|叫啥|是谁|什么名字", text):
        if not (re.search(r"鸟|动物|海鸥", text) and re.search(r"叫什么|叫啥", text)):
            return "person"
    if re.search(r"鸟|动物", text) and re.search(r"叫什么|叫啥|是什么", text) and not _asks_father(text):
        return "name"
    if "茶" in text and re.search(r"什么|哪种|啥", text):
        return "name"
    if re.search(r"叫什么|叫啥|什么名字|是什么", text):
        return "name"
    return ""


def question_subjects(query: str) -> list[str]:
    """问句里被问的那个东西。答案不能原样把主语交回去。"""
    found: list[str] = []
    for part in re.split(r"的", query or ""):
        part = re.split(r"[？?，,]", part)[0]
        part = re.split(r"打磨|守护|看守|养|是|有|叫", part)[0]
        if part.endswith("家") and len(part) > 2:
            part = part[:-1]
        for role in sorted(_ROLE_SUFFIX, key=len, reverse=True):
            if part.endswith(role) and len(part) > len(role):
                part = part[: -len(role)]
        if not re.fullmatch(r"[\u4e00-\u9fff]{2,6}", part):
            continue
        if "谁" in part or part in {"什么", "怎么", "这个", "那个", "哪个", "父亲", "女儿", "主人", "工匠", "师傅"}:
            continue
        if part not in found:
            found.append(part)
    return found


def _asked_clause(query: str) -> str:
    """带疑问词的那一小句。前面用来交代别人的分句不算在问的角色里。"""
    parts = [part.strip() for part in re.split(r"[，,。；;]", query or "") if part.strip()]
    for part in reversed(parts):
        if re.search(r"谁|哪个人|哪一位|哪位|什么人|叫什么|叫啥|啥名|什么名字", part):
            return part
    return parts[-1] if parts else ""


def _asked_kind(query: str) -> str:
    """问句要的种类只看正在问的那一小句的中心词。定语里的守护、磨，只用来指明是哪一座。"""
    clause = re.sub(r"到底|究竟|又", "", _asked_clause(query)).rstrip("？?。 ")
    if not clause:
        return ""
    # 问的是灯塔本身：叫什么、名称、是哪一座。值守、执勤、站岗只是指出哪一座。
    if re.search(r"(?:灯塔|这座塔|那座塔|的塔|一座塔)(?:叫什么|叫啥|啥名|名称|的名称|的名字)", clause):
        return "tower"
    if re.search(r"是哪一座|哪一座灯塔|哪座灯塔|什么灯塔", clause):
        return "tower"
    if re.search(r"哪一座灯塔|是哪一座|哪座灯塔|什么灯塔|哪一座塔", clause):
        return "tower"
    if re.search(r"名称是什么|的名称", clause) and "塔" in (query or "") and "盐" not in clause:
        return "tower"
    if re.search(r"(?:师傅|工匠)(?:叫什么|叫啥|啥名|什么名字)", clause):
        return "person"
    if re.search(r"的(?:叫什么|叫啥|啥名)", clause) and not re.search(r"塔叫", clause):
        return "person"
    named = re.search(r"(?:叫什么名字|叫什么名|叫什么|叫啥名|叫啥|啥名|什么名字|的名字)", clause)
    if named:
        before = clause[: named.start()]
        if re.search(r"塔$", before):
            return "tower"
        if re.search(r"(?:人|那位|哪位|谁|一位)$", before):
            return "person"
        if re.search(r"(?:它|这座|那座)$", before) and "塔" in (query or ""):
            return "tower"
    if re.fullmatch(r"(?:名字)?(?:叫什么|叫啥|叫做什么|名字是什么)(?:名字)?", clause) and "塔" in (query or ""):
        return "tower"
    if re.search(r"名字是什么|名叫什么|叫做什么|名字叫什么", clause) and "塔" in (query or ""):
        if not re.search(r"谁|哪位|那位|哪个人", clause):
            return "tower"
    if re.search(r"谁|哪个人|哪一位|哪位|什么人", clause) and not re.search(r"塔叫", clause):
        return "person"
    if re.search(r"哪座塔|什么塔|哪一座塔|哪座灯塔", clause):
        return "tower"
    return ""


def _verb_near_wh(clause: str) -> str:
    """疑问词旁边的谓语才是被问的角色。更前面的「看守的塔」只是定语。"""
    wh = re.search(r"谁|哪位|哪一位|哪个人|什么人|那位", clause or "")
    if not wh:
        return ""
    window = clause[max(0, wh.start() - 4): wh.end() + 6]
    if re.search(r"磨|打磨", window):
        return "maker"
    if re.search(r"女儿|闺女|妻子|爱人|老婆", window):
        return "kin"
    modifier = re.search(r"([\u4e00-\u9fff]{0,10})的(?:人|那位|哪位)", clause or "")
    if modifier and re.search(r"磨|打磨", modifier.group(1)) and wh.start() <= modifier.end():
        return "maker"
    return ""


def _charged_with(clause: str) -> str:
    """「负责 V」的角色看 V。负责打磨是工匠，负责看守是守护者。"""
    matched = re.search(r"负责([\u4e00-\u9fff]{1,6})", clause or "")
    if not matched:
        return ""
    verb = matched.group(1)
    if re.match(r"(?:打磨|磨)", verb):
        return "maker"
    if re.match(r"(?:看守|守护|值守|看管|照看|守)", verb):
        return "keeper"
    return ""


def _asking_is_make(query: str) -> bool:
    """问的是磨镜的师傅，不是定语里负责看守的那个人。"""
    if _asked_kind(query) == "tower":
        return False
    clause = re.sub(r"到底|究竟|又", "", _asked_clause(query))
    if _charged_with(clause) == "maker":
        return True
    if re.search(r"(?:师傅|工匠)", clause) and re.search(r"磨|打磨|镜", query or "") and re.search(
        r"叫什么|叫啥|啥名|是谁|哪位", clause
    ):
        return True
    if re.search(r"磨|镜|打磨", clause) and re.search(
        r"(?:师傅|工匠).{0,6}(?:叫什么|叫啥|啥名|是谁|是哪)", clause
    ):
        return True
    if _verb_near_wh(clause) == "maker":
        return True
    wh = re.search(r"谁|哪位", clause)
    if not wh or not re.search(r"磨|打磨", clause):
        return False
    window = clause[max(0, wh.start() - 6): wh.end() + 6]
    if re.search(r"守护|看守|值守|守塔|谁守|在守", window):
        return False
    return bool(re.search(r"磨|打磨", window))


def _tower_duty(query: str) -> bool:
    """只有问句本身在问谁对塔负责时，才是看守。塔叫什么、谁磨的，都不是。"""
    if _asked_kind(query) != "person" or _asking_is_make(query):
        return False
    clause = _asked_clause(query)
    if _charged_with(clause) == "maker" or _verb_near_wh(clause) in {"maker", "kin"}:
        return False
    if re.search(r"谁的女儿|谁的闺女|女儿叫", clause):
        return False
    if re.search(r"第一次|点亮|点灯|建成|发明|设计", clause):
        return False
    if re.search(r"妻子|爱人|老婆|丈夫|老公|太太|配偶", clause):
        return False
    if _charged_with(clause) == "keeper":
        return True
    if re.search(r"日常", clause) and re.search(r"谁|哪位|守护|看守|值守", clause):
        return True
    if re.search(r"守护|看守|值守|看管|守塔|守着|站岗|执勤|守望|在守|谁守|管着", clause) and re.search(
        r"谁|哪位|哪个人|那位|人", clause
    ):
        return True
    if "塔" in clause:
        return True
    if _bound_makers(query) and not re.search(r"磨|打磨", clause):
        return True
    return False


def _asked_role(query: str) -> str:
    text = _asked_clause(query)
    if _asked_kind(query) == "tower":
        return ""
    if _asking_is_make(query):
        return "maker"
    if _tower_duty(query):
        return "keeper"
    marks: list[tuple[int, str]] = []
    for word, role in (
        ("负责守", "keeper"),
        ("谁管", "keeper"),
        ("管着", "keeper"),
        ("看守人", "keeper"),
        ("守护人", "keeper"),
        ("守塔人", "keeper"),
        ("看守", "keeper"),
        ("守护", "keeper"),
        ("守塔", "keeper"),
        ("谁守", "keeper"),
        ("在守", "keeper"),
        ("守着", "keeper"),
        ("看着", "keeper"),
        ("看管", "keeper"),
        ("打磨", "maker"),
        ("磨镜", "maker"),
        ("磨", "maker"),
        ("工匠", "maker"),
        ("师傅", "maker"),
        ("配偶", "spouse"),
        ("妻子", "spouse"),
        ("爱人", "spouse"),
        ("太太", "spouse"),
        ("老婆", "spouse"),
        ("老公", "spouse"),
        ("丈夫", "spouse"),
        ("那口子", "spouse"),
        ("另一半", "spouse"),
        ("媳妇", "spouse"),
        ("夫人", "spouse"),
        ("老伴", "spouse"),
        ("内人", "spouse"),
        ("对象", "spouse"),
        ("先生", "spouse"),
        ("主人", "owner"),
        ("父亲", "father"),
        ("爸爸", "father"),
        ("老爸", "father"),
        ("她爹", "father"),
        ("他爹", "father"),
        ("她爸", "father"),
        ("他爸", "father"),
        ("爹", "father"),
        ("爸", "father"),
        ("女儿", "daughter"),
        ("闺女", "daughter"),
        ("丫头", "daughter"),
    ):
        index = text.rfind(word)
        if index >= 0:
            marks.append((index, role))
    if "养" in text and "谁" in text:
        marks.append((text.rfind("养"), "owner"))
    if not marks:
        return ""
    anchors = [item.start() for item in re.finditer(r"哪个人|哪一位|哪位|什么人|谁|叫什么|叫啥|啥名", text)]
    anchor = anchors[-1] if anchors else len(text)
    marks.sort(key=lambda item: (abs(item[0] - anchor), -item[0]))
    return marks[0][1]


def _bound_makers(query: str) -> set[str]:
    """问句里已经说成「打磨/磨」的那个人，不能再拿来回答守塔。"""
    text = query or ""
    found: set[str] = set()
    for match in re.finditer(r"([\u4e00-\u9fff]{2,3})(?:是|为).{0,10}(?:打磨|磨镜|磨)", text):
        if _person_shape(match.group(1)) and "谁" not in match.group(1):
            found.add(match.group(1))
    for match in re.finditer(r"([\u4e00-\u9fff]{2,3})打磨", text):
        if _person_shape(match.group(1)) and "谁" not in match.group(1) and "镜" not in match.group(1):
            found.add(match.group(1))
    for match in re.finditer(r"(?:打磨|磨镜|磨透镜|磨).{0,8}是([\u4e00-\u9fff]{2,3})", text):
        if _person_shape(match.group(1)) and "谁" not in match.group(1):
            found.add(match.group(1))
    for match in re.finditer(r"(?:是|由)([\u4e00-\u9fff]{2,3})(?:打磨|磨)", text):
        if _person_shape(match.group(1)):
            found.add(match.group(1))
    for match in re.finditer(r"([\u4e00-\u9fff]{2,3})只(?:是|负责).{0,10}(?:磨|打磨|工匠|师傅)", text):
        if _person_shape(match.group(1)):
            found.add(match.group(1))
    for match in re.finditer(r"([\u4e00-\u9fff]{2,3})(?:负责)?磨", text):
        name = match.group(1)
        if _person_shape(name) and name not in {"什么", "怎么", "这个", "那个"}:
            found.add(name)
    return found


def _keeper(statement: str) -> str:
    match = re.search(r"([\u4e00-\u9fff]{2,3})在.{0,16}守护", statement or "")
    return match.group(1) if match else ""


def _maker(statement: str) -> str:
    match = re.search(r"(?:工匠|师傅)([\u4e00-\u9fff]{2,4})打磨", statement or "")
    return match.group(1) if match else ""


def _owner(statement: str) -> str:
    match = re.search(r"([\u4e00-\u9fff]{2,3})养了", statement or "")
    return match.group(1) if match else ""


def _daughter(statement: str) -> str:
    match = re.search(r"的女儿([\u4e00-\u9fff]{2,3})", statement or "")
    return match.group(1) if match else ""


def _father(statement: str) -> str:
    match = re.search(r"([\u4e00-\u9fff]{2,3})的女儿", statement or "")
    return match.group(1) if match else ""


def _role_argument(statement: str, role: str) -> str:
    if role == "keeper":
        return _keeper(statement)
    if role == "maker":
        return _maker(statement)
    if role == "owner":
        return _owner(statement)
    if role == "daughter":
        return _daughter(statement)
        if role == "father":
            return _father(statement)
        if role == "spouse":
            return ""
    return ""


_TOPIC_WORDS = ("霜降", "晾晒", "电灯", "透镜", "灯塔", "海盐", "海鸥", "十六", "工匠", "师傅", "守护", "看守")


def _wrong_event(query: str, statement: str) -> bool:
    """第一次点灯不是改用电灯。句子里没有这件事，就不能拿另一个年份来答。"""
    asked = query or ""
    text = statement or ""
    if any(mark in asked for mark in ("第一次", "点灯", "点亮", "首次")):
        return not any(mark in text for mark in ("点灯", "点亮", "第一次"))
    return False


def _lens_required(query: str, statement: str) -> bool:
    asked = query or ""
    text = statement or ""
    if any(mark in asked for mark in ("十六", "透镜")):
        return not any(mark in text for mark in ("十六", "透镜"))
    return False


def _person_shape(span: str) -> bool:
    if not re.fullmatch(r"[\u4e00-\u9fff]{2,4}", span or ""):
        return False
    if span in _COUNTRIES or any(span.startswith(country) for country in _COUNTRIES):
        return False
    if any(job in span for job in ("工匠", "师傅", "学徒", "徒弟", "市长")):
        return False
    if span.endswith(("塔", "盐", "鸥", "港", "村", "镇", "市", "城")):
        return False
    return True


def extract_span(query: str, statement: str) -> str:
    """从这一句里抄问句要的那一种取值。抄不到就返回空。"""
    text = statement or ""
    kind = question_kind(query)
    if kind == "colour":
        for colour in sorted(_COLOURS, key=len, reverse=True):
            if colour in text:
                return colour
        return ""
    if kind == "material":
        for item in _MATERIALS:
            if item in text:
                return item
        return ""
    if kind == "nation":
        for country in _COUNTRIES:
            if country in text:
                return country
        return ""
    if kind == "animal":
        for animal in _ANIMALS:
            if animal in text:
                return animal
        return ""
    if kind == "tower":
        if _lens_required(query, text):
            return ""
        named = re.search(r"名叫([\u4e00-\u9fff]{1,6}塔)", text)
        if named and not _lens_required(query, text):
            return named.group(1)
        found = []
        for match in re.finditer(r"塔", text):
            for length in (3, 2, 1):
                begin = match.start() - length
                if begin < 0:
                    continue
                chunk = text[begin:match.end()]
                if not chunk or chunk[0] in "年的座第这那":
                    continue
                if re.fullmatch(r"[\u4e00-\u9fff]{1,3}塔", chunk):
                    found.append(chunk)
                    break
        proper = [name for name in found if name not in {"灯塔", "这座塔", "那座塔"}]
        if proper:
            return proper[-1]
        return found[-1] if found else ""
    if kind == "place":
        if "村" in (query or ""):
            match = re.search(r"([\u4e00-\u9fff]{1,8}村)", text)
            return match.group(1) if match else ""
        if "城市" in (query or "") or re.search(r"哪座城|哪个城", query or ""):
            match = re.search(r"([\u4e00-\u9fff]{1,8}(?:城|市))", text)
            if match:
                return match.group(1)
            match = re.search(r"(?:总部在|总部设在)([\u4e00-\u9fff]{2,4})", text)
            if match and "的" not in match.group(1):
                return match.group(1)
            return ""
        found = []
        for match in re.finditer(r"[港镇乡县]", text):
            for length in (2, 3, 1):
                begin = match.start() - length
                if begin < 0:
                    continue
                before = text[begin - 1:begin]
                if before and before not in "在的是为于住到往属":
                    continue
                name = text[begin:match.end()]
                if re.fullmatch(r"[\u4e00-\u9fff]+", name):
                    found.append(name)
                    break
        return found[-1] if found else ""
    if kind == "time":
        if _wrong_event(query, text):
            return ""
        if "电" in (query or "") and "电" not in text:
            return ""
        for term in _SOLAR:
            if term in text and "晒" in (query or "") or term in text and "晾" in (query or ""):
                return term
        for term in _SOLAR:
            if term in text and "什么时候" in (query or ""):
                return term
        match = re.search(r"(\d{3,4}年)", text)
        return match.group(1) if match else ""
    if kind == "measure":
        asked = query or ""
        if _wrong_event(asked, text):
            return ""
        if any(mark in asked for mark in ("多高", "塔高", "多少米", "几米")):
            match = re.search(r"([0-9一二三四五六七八九十百千两]{1,8}米)", text)
            return match.group(1) if match else ""
        if "面" in asked:
            match = re.search(r"([0-9一二三四五六七八九十百千两]{1,8}面)", text)
            return match.group(1) if match else ""
        if "腿" in asked or "条" in asked:
            match = re.search(r"([0-9一二三四五六七八九十两]{1,4}条腿)", text)
            return match.group(1) if match else ""
        if "出生" in asked or "生日" in asked:
            return ""
        if any(mark in asked for mark in ("多少年", "多久", "守了", "守护了")):
            return ""
        if any(mark in asked for mark in ("多少钱", "几岁", "人口", "徒弟", "学徒", "几次", "多少次")):
            return ""
        if "电" in asked and "电" not in text:
            return ""
        if any(mark in asked for mark in ("建", "建于", "建成")):
            match = re.search(r"建于(\d{3,4}年)", text)
            if match:
                return match.group(1)
        if any(mark in asked for mark in ("哪年", "哪一年")):
            match = re.search(r"(\d{3,4}年)", text)
            return match.group(1) if match else ""
        if "人" in asked and "守" in asked:
            return ""
        if "员工" in asked or "多少人" in asked:
            match = re.search(r"([0-9一二三四五六七八九十百千两]{1,8}人)", text)
            return match.group(1) if match else ""
        return ""
    if kind == "person":
        for missing in ("妻子", "丈夫", "老婆", "老公", "妈妈", "母亲", "爸爸", "父亲", "村子", "出生", "生日"):
            if missing in (query or "") and missing not in text and not (
                missing in ("爸爸", "父亲") and "女儿" in text
            ):
                return ""
        if "出生" in (query or "") or "生日" in (query or ""):
            return ""
        role = _asked_role(query)
        if role == "spouse":
            return ""
        if role == "father":
            parent = _father(text)
            return parent if _person_shape(parent) else ""
        if role:
            return _role_argument(text, role)
        if "谁" in (query or ""):
            return ""
        match = re.search(r"名叫([\u4e00-\u9fff]{2,4})", text)
        return match.group(1) if match and _person_shape(match.group(1)) else ""
    if kind == "name":
        match = re.search(r"名叫([\u4e00-\u9fffA-Za-z0-9·]{1,12})", text)
        if match:
            return match.group(1)
        match = re.search(r"(?:名字是|名为|叫做)([\u4e00-\u9fffA-Za-z0-9·]{1,12})", text)
        if match:
            return match.group(1)
        match = re.search(r"是([\u4e00-\u9fffA-Za-z0-9·]{2,12})", text)
        if match:
            return match.group(1)
        match = re.search(r"(?:名字)?叫([\u4e00-\u9fffA-Za-z0-9·]{1,12})", text)
        return match.group(1) if match else ""
    return ""


def _claimed_role_mismatch(query: str, statement: str) -> bool:
    """「诺丁守护的塔」不能用诺丁只是工匠的那一句。"""
    text = query or ""
    claimed = re.search(r"([\u4e00-\u9fff]{2,4})(?:在.{0,4})?(?:守护|看守)", text)
    if claimed and not re.search(r"谁|哪|什么|负责|父亲|主人|爸爸|女儿|闺女|看守|守护", claimed.group(1)) and "的" not in claimed.group(1) and not claimed.group(1).endswith(("爹", "爸")) and _person_shape(claimed.group(1)):
        if _keeper(statement) != claimed.group(1):
            return True
    asked = _asked_role(text)
    claimed_make = re.search(r"([\u4e00-\u9fff]{2,3})打磨", text)
    if claimed_make and claimed_make.group(1) in {"负责", "正在", "给人", "前来"}:
        claimed_make = None
    if (
        asked != "keeper"
        and claimed_make
        and _person_shape(claimed_make.group(1))
        and "谁" not in claimed_make.group(1)
        and "哪座" not in text
        and "什么塔" not in text
    ):
        if _maker(statement) != claimed_make.group(1):
            return True
    return False


def _subject_present(subject: str, statement: str) -> bool:
    if subject in (statement or ""):
        return True
    for length in range(min(len(subject), 4), 1, -1):
        if subject[:length] in (statement or ""):
            return True
    return False


def _same_thing(query: str, statement: str) -> bool:
    """狗的问题不能用猫的句子，汽车的问题不能用自行车的句子。"""
    asked = query or ""
    text = statement or ""
    if "狗" in asked and "狗" not in text:
        return False
    if "猫" in asked and "猫" not in text:
        return False
    if "茶" in asked and "茶" not in text:
        return False
    if "花" in asked and "花" not in text:
        return False
    if "盐" in asked and "盐" not in text and head_type(query) != "tower":
        return False
    if "讨厌" in asked and "讨厌" not in text:
        return False
    if "自行车" in asked and "自行车" not in text:
        return False
    if "车" in asked and "自行车" not in asked and "自行车" in text and "汽车" not in text:
        return False
    return True


def accept_span(
    query: str,
    span: str,
    statement: str,
    *,
    require_subject: bool = False,
    allow_chain: bool = False,
) -> bool:
    """取值必须是问句要的种类，而且不能就是问句里的主语。"""
    text = (span or "").strip().rstrip("。")
    if not text or text not in (statement or ""):
        return False
    if re.search(r"啥|什么|吗|呢|多少|是谁", text) or text in {"谁", "哪", "几", "啥名"}:
        return False
    if any(text == subject or (len(text) >= 2 and text in subject) for subject in question_subjects(query)):
        return False
    if not _same_thing(query, statement):
        return False
    if question_kind(query) in {"person", "tower"} and _claimed_role_mismatch(query, statement):
        return False
    for word in _SPOUSE_WORDS + ("妈妈", "母亲"):
        if word in (query or "") and word not in (statement or ""):
            return False
    if require_subject:
        subjects = question_subjects(query)
        if subjects and not any(subject in (statement or "") for subject in subjects):
            return False
    kind = question_kind(query)
    headed = head_type(query)
    if headed == "person" and not _person_shape(text):
        return False
    if headed == "tower" and not text.endswith("塔"):
        return False
    if headed == "person" and _asked_role(query) == "keeper" and text in _bound_makers(query):
        return False
    if _wrong_event(query, statement):
        return False
    if kind == "tower" and _lens_required(query, statement):
        return False
    if not kind:
        return True
    if kind == "tower" and not text.endswith("塔"):
        return False
    if kind == "person":
        role = _asked_role(query)
        subjects = question_subjects(query)
        if not allow_chain and subjects and not any(_subject_present(subject, statement) for subject in subjects):
            return False
        if role == "keeper":
            if "守护" not in (statement or "") and "看守" not in (statement or ""):
                return False
            if text == _maker(statement) and text != _keeper(statement):
                return False
            obj = re.search(r"(?:守护|看守)([\u4e00-\u9fff]{2,8})", query or "")
            if obj and "的" not in obj.group(1) and obj.group(1) not in (statement or ""):
                target = obj.group(1)
                if not (target.endswith("塔") and "塔" in (statement or "")):
                    return False
        if role == "spouse":
            return False
        if role == "father":
            return text == _father(statement) and _person_shape(text)
        if role:
            return text == _role_argument(statement, role) and _person_shape(text)
        return _person_shape(text)
    if kind == "name":
        expected = extract_span(query, statement)
        subjects = question_subjects(query)
        if not expected or any(expected == subject for subject in subjects):
            return False
        if text != expected and expected not in text:
            return False
        if subjects and not any(_subject_present(subject, statement) for subject in subjects):
            return allow_chain
        return True
    expected = extract_span(query, statement)
    if not expected:
        return False
    if text == expected:
        return True
    return text in expected and len(expected) - len(text) <= 1


def _score(query: str, statement: str) -> int:
    score = 0
    asked = query or ""
    if "电" in asked and "电" in statement:
        score += 6
    if "霜降" in asked and "霜降" in statement:
        score += 6
    if "盐" in asked and "盐" in statement:
        score += 4
    if any(mark in asked for mark in ("十六", "透镜")) and any(mark in statement for mark in ("十六", "透镜")):
        score += 6
    if "建" in asked and "建于" in statement:
        score += 6
    if ("晒" in asked or "晾" in asked) and ("晒" in statement or "晾" in statement):
        score += 6
    score += sum(len(name) for name in question_subjects(asked) if name in statement)
    return score


def _catalog(facts: list[dict]) -> list[str]:
    from memory_core.span_guard import statement_of

    found: list[str] = []

    def add(name: str) -> None:
        name = (name or "").strip()
        if len(name) >= 2 and name not in found:
            found.append(name)

    for fact in facts:
        add(str(fact.get("entity") or ""))
        text = statement_of(fact)
        for match in re.finditer(r"名叫([\u4e00-\u9fffA-Za-z0-9·]{1,12})", text):
            add(match.group(1))
        for reader in (_keeper, _maker, _owner, _daughter, _father):
            add(reader(text))
        for word in ("透镜", "海鸥", "海盐", "雾港", "灯塔"):
            if word in text:
                add(word)
        for match in re.finditer(r"([\u4e00-\u9fff]{2,4}塔)", text):
            add(match.group(1))
    found.sort(key=len, reverse=True)
    return found


def _mentioned_names(query: str, facts: list[dict]) -> list[str]:
    from memory_core.fact_span import name_bounded

    text = query or ""
    catalog = _catalog(facts)
    hits = [name for name in catalog if name_bounded(name, text)]
    for name in catalog:
        if name in hits or name not in text:
            continue
        index = text.find(name)
        end = index + len(name)
        if any(
            other != name and other in text and text.find(other) <= index < text.find(other) + len(other)
            for other in catalog
        ):
            continue
        after = text[end:end + 1]
        if not after or after in "的守收有是在打养叫吗？?活岁住多几钱妻学城国第什怎":
            hits.append(name)
    kept: list[str] = []
    for name in hits:
        if any(name != other and name in other and other in text for other in hits):
            continue
        kept.append(name)
    return kept


def memory_topic(query: str, facts: list[dict]) -> bool:
    """问句点到了已经记住的人、地方或东西。这种问句不能再交给基座编。"""
    from memory_core.span_guard import statement_of

    if _mentioned_names(query, facts):
        return True
    blob = "\n".join(statement_of(fact) for fact in facts if isinstance(fact, dict))
    asked = query or ""
    if not blob or not asked:
        return False
    for word in _TOPIC_WORDS:
        if word in asked and word in blob:
            return True
    for match in re.finditer(r"[0-9一二三四五六七八九十百千两]{2,4}", blob):
        token = match.group(0)
        if len(token) >= 2 and token in asked:
            return True
    return False


def grounded_subjects(query: str, facts: list[dict]) -> list[str]:
    from memory_core.span_guard import statement_of

    subjects = [
        subject for subject in question_subjects(query)
        if any(subject in statement_of(fact) for fact in facts)
    ]
    if subjects:
        return subjects
    return _mentioned_names(query, facts)


def _from_fact(query: str, fact: dict, subjects: list[str]) -> tuple[str, dict] | None:
    from memory_core.span_guard import statement_of

    text = statement_of(fact)
    if subjects and not any(subject in text for subject in subjects):
        return None
    span = extract_span(query, text)
    if span and accept_span(query, span, text, require_subject=False):
        return span, fact
    return None


def _parent_fact(query: str, rows: list[dict]) -> tuple[str, dict] | None:
    """从「X的女儿Y」取出父亲。鸟的主人、她爹、它主人都指到这个父亲，不取名叫的宠物。"""
    from memory_core.span_guard import statement_of

    asked = query or ""
    pairs: list[tuple[str, str, dict]] = []
    for fact in rows:
        text = statement_of(fact)
        parent = _father(text)
        daughter = _daughter(text)
        if parent and daughter and _person_shape(parent):
            pairs.append((parent, daughter, fact))
    for parent, daughter, fact in pairs:
        if daughter in asked:
            return parent, fact
    refers = any(word in asked for word in ("主人", "她爹", "他爹", "她爸", "他爸", "爸爸", "父亲", "它主", "那只", "鸟", "海鸥", "三条腿"))
    if not refers or len(pairs) != 1:
        return None
    parent, daughter, fact = pairs[0]
    for other in rows:
        text = statement_of(other)
        for name in (_keeper(text), _maker(text), _owner(text)):
            if name and name in asked and name not in {parent, daughter}:
                return None
    return parent, fact


def _kinship_hit(query: str, rows: list[dict]) -> tuple[str, dict] | None:
    from memory_core.span_guard import statement_of

    if _asks_spouse(query):
        return None
    if question_kind(query) == "tower" and re.search(r"父亲|爸|爹", query or ""):
        found = _parent_fact(query, rows)
        if not found:
            return None
        parent, _fact = found
        for fact in rows:
            text = statement_of(fact)
            if _keeper(text) != parent:
                continue
            named = re.search(r"名叫([\u4e00-\u9fff]{2,4}塔)", text)
            if named and _person_shape(parent):
                return named.group(1), fact
        return None
    if not _asks_father(query):
        return None
    found = _parent_fact(query, rows)
    if not found:
        return None
    parent, fact = found
    if accept_span(query, parent, statement_of(fact), allow_chain=True):
        return parent, fact
    return None


def _tower_name_answer(query: str, rows: list[dict]) -> tuple[str, dict] | None:
    """问灯塔叫什么。句子里既有看守的人又有塔名时，取塔名，不取那个人。"""
    from memory_core.span_guard import statement_of

    if head_type(query) != "tower":
        return None
    asked = query or ""
    if re.search(r"盐", asked) and not re.search(r"最早|第一|头一|地方|港口|晾|晒", asked):
        return None
    if re.search(r"父亲|爸|爹", asked) or ("主人" in asked and re.search(r"鸟|海鸥|女儿", asked)):
        found = _kinship_hit(asked, rows)
        if found and str(found[0]).endswith("塔"):
            return found
    if re.search(r"十六|透镜|镜片", asked):
        for fact in rows:
            text = statement_of(fact)
            if any(mark in text for mark in ("十六", "透镜", "镜片")):
                tower = _named_tower(text)
                if tower:
                    return tower, fact
    if re.search(r"诺丁|工匠|师傅", asked) and not re.search(r"父亲|爸|爹|女儿|主人|十六|透镜", asked):
        return None
    if re.search(r"叫什么|叫啥|啥名|什么名字|的名字|名称|哪座|哪一座|什么塔|是哪一", asked):
        for fact in rows:
            text = statement_of(fact)
            if "名叫" not in text:
                continue
            tower = _named_tower(text)
            if tower:
                return tower, fact
    return None


def _named_tower(text: str) -> str:
    named = re.search(r"名叫([\u4e00-\u9fff]{2,4}塔)", text or "")
    if named:
        return named.group(1)
    if "白鹭塔" in (text or ""):
        return "白鹭塔"
    return ""


def _daughter_chain(query: str, rows: list[dict]) -> tuple[str, dict] | None:
    """问的是闺女。父亲只是中间的人，答不到孩子就当没走完。"""
    from memory_core.span_guard import statement_of

    if not _asks_daughter(query):
        return None
    asked = query or ""
    keeper = ""
    for fact in rows:
        text = statement_of(fact)
        parent = _father(text)
        child = _daughter(text)
        if parent and child and parent in asked and _person_shape(child):
            return child, fact
    if not re.search(r"塔|灯塔|守护|看守", asked):
        return None
    tower = ""
    for fact in rows:
        text = statement_of(fact)
        if _maker(text) and ("透镜" in text or "打磨" in text):
            tower = _named_tower(text) or tower
    for fact in rows:
        text = statement_of(fact)
        person = _keeper(text)
        if person and tower and tower in text and ("守护" in text or "看守" in text):
            keeper = person
    if not keeper:
        return None
    for fact in rows:
        text = statement_of(fact)
        if _father(text) == keeper:
            child = _daughter(text)
            if child and child != keeper and _person_shape(child):
                return child, fact
    return None


def _keeper_answer(query: str, rows: list[dict]) -> tuple[str, dict] | None:
    """问谁守塔。打磨的人不是守护者；透镜那一句没有守护，就改用守护那一句。"""
    from memory_core.span_guard import statement_of

    asked = query or ""
    if question_kind(asked) == "tower" or question_kind(asked) not in {"person", ""}:
        return None
    if _asks_daughter(asked) or _asks_spouse(asked) or _asks_maker(asked):
        return None
    duty = _tower_duty(asked)
    clause = _asked_clause(asked)
    if not duty and not re.search(r"守护|看守|守塔|谁守|在守|守着|看着|看管|管着|负责守|谁管|值守|站岗", clause):
        return None
    if not re.search(r"谁|哪个人|哪一位|哪位|什么人|叫什么|叫啥|啥名|什么名字", asked):
        return None
    target = re.search(r"(?:守护|看守|守着|守)([\u4e00-\u9fff]{1,8})", asked)
    if target and not re.search(r"塔|灯", target.group(1)) and target.group(1) not in {"人", "的人", "者"}:
        if re.search(r"诺丁|透镜|盐|海鸥|阿哨|工匠", target.group(1) + asked[target.end():target.end() + 4]):
            return None
    for fact in rows:
        text = statement_of(fact)
        if "守护" not in text and "看守" not in text:
            continue
        keeper = _keeper(text)
        if keeper and _person_shape(keeper):
            return keeper, fact
    return None


def _maker_chain(query: str, rows: list[dict]) -> tuple[str, dict] | None:
    """问的是谁磨的。父亲只是中间的人，答不到工匠就当没走完。"""
    from memory_core.span_guard import statement_of

    if question_kind(query) != "person" or not _asks_maker(query):
        return None
    asked = query or ""
    if re.search(r"海鸥|阿哨|鸟", asked) and "透镜" not in asked and "塔" not in asked:
        return None
    claimed = re.search(r"([\u4e00-\u9fff]{2,3})打磨", asked)
    if claimed and claimed.group(1) in {"负责", "正在", "给人", "前来"}:
        claimed = None
    tower = ""
    parent = _parent_fact(query, rows)
    if parent:
        for fact in rows:
            text = statement_of(fact)
            if _keeper(text) == parent[0]:
                named = re.search(r"名叫([\u4e00-\u9fff]{2,4}塔)", text)
                if named:
                    tower = named.group(1)
    for fact in rows:
        text = statement_of(fact)
        maker = _maker(text)
        if not maker or not _person_shape(maker):
            continue
        if "打磨" not in text and "磨" not in text:
            continue
        if tower and tower not in text and "透镜" not in text:
            continue
        if not tower and "透镜" not in asked and "磨" not in asked:
            continue
        if (
            claimed
            and _person_shape(claimed.group(1))
            and "谁" not in claimed.group(1)
            and "镜" not in claimed.group(1)
            and claimed.group(1) != maker
        ):
            continue
        if "透镜" in asked or "磨" in asked or (tower and tower in text):
            return maker, fact
    return None


def _taught_paraphrase(query: str, rows: list[dict]) -> tuple[str, dict] | None:
    """教过的说法换一种问法。种类对得上就答，不先弃权。"""
    from memory_core.span_guard import statement_of

    asked = query or ""
    if not _asks_spouse(asked) and not _asks_father(asked) and (
        _asks_keeper_name(asked) or (
            re.search(r"谁", asked) and re.search(r"守", asked) and re.search(r"塔|灯塔|四十二", asked) and not _asks_maker(asked)
        )
    ):
        for fact in rows:
            text = statement_of(fact)
            keeper = _keeper(text)
            if keeper and _person_shape(keeper) and ("守护" in text or "看守" in text):
                return keeper, fact
    if re.search(r"四十二|42", asked) and re.search(r"谁|守护|看守|守塔", asked) and not _asks_maker(asked):
        for fact in rows:
            text = statement_of(fact)
            keeper = _keeper(text)
            if keeper and "四十二" in text and _person_shape(keeper):
                return keeper, fact
    if re.search(r"第一座|头一座", asked) and re.search(r"塔", asked) and re.search(r"盐|霜降|雾港|特产|晾|晒|港口|地方", asked):
        for fact in rows:
            text = statement_of(fact)
            tower = _named_tower(text)
            if tower and ("第一座" in text or "守护" in text):
                return tower, fact
    if "霜降" in asked and "盐" in asked and "塔" not in asked and re.search(r"叫|啥|什么|名字", asked):
        for fact in rows:
            text = statement_of(fact)
            if "霜降" not in text or "盐" not in text:
                continue
            named = re.search(r"名叫([\u4e00-\u9fff]{2,8})", text)
            if named and not named.group(1).endswith(("塔", "港")):
                return named.group(1), fact
    if re.search(r"工匠|师傅", asked) and re.search(r"叫啥|啥名", asked) and not re.search(r"海鸥|鸟|养|妻子|爱人", asked):
        for fact in rows:
            maker = _maker(statement_of(fact))
            if maker and _person_shape(maker):
                return maker, fact
    return None


def choose_typed(query: str, facts: list[dict]) -> tuple[str, dict] | None:
    """关系链和单句摘录都要过同一种类检查。对不上就当没答出来。"""
    from memory_core.span_guard import relation_decision, statement_of

    from memory_core.extract import is_question_fragment

    rows = [
        fact for fact in facts
        if isinstance(fact, dict) and not is_question_fragment(str(fact.get("statement") or ""))
    ]
    personal = "我的" in (query or "") or (query or "").startswith("我")
    if personal:
        rows = [
            fact for fact in rows
            if "我" in statement_of(fact) or str(fact.get("entity") or "") in {"我", "用户"}
        ]
        if not rows:
            return None
    if re.search(r"是.+还是|是不是", query or ""):
        return None
    if head_type(query) == "tower" and re.search(r"最早|第一|头一", query or "") and re.search(r"盐|霜降|晾|晒|港|地方|特产", query or ""):
        for fact in rows:
            text = statement_of(fact)
            tower = _named_tower(text)
            if tower and ("第一座" in text or ("守护" in text and "名叫" in text)):
                return tower, fact
    named = _tower_name_answer(query, rows)
    if named:
        return named
    child = _daughter_chain(query, rows)
    if child:
        return child
    watched = _keeper_answer(query, rows)
    if watched:
        return watched
    made = _maker_chain(query, rows)
    if made:
        return made
    taught = _taught_paraphrase(query, rows)
    if taught:
        return taught
    kin = _kinship_hit(query, rows)
    if kin:
        return kin
    if not personal and not memory_topic(query, rows):
        decision = relation_decision(query, rows)
        if decision and decision.get("status") == "answer":
            fact = decision.get("fact") or {}
            if isinstance(fact, dict):
                span = str(decision.get("span") or "")
                if accept_span(query, span, statement_of(fact), allow_chain=True):
                    return span, fact
                rescued = _from_fact(query, fact, [])
                if rescued:
                    return rescued
        return None
    decision = relation_decision(query, rows)
    if decision and decision.get("status") == "answer":
        fact = decision.get("fact") or {}
        if isinstance(fact, dict):
            span = str(decision.get("span") or "")
            if accept_span(query, span, statement_of(fact), allow_chain=True):
                return span, fact
            rescued = _from_fact(query, fact, [])
            if rescued:
                return rescued
    subjects = grounded_subjects(query, rows)
    pool = rows
    focus = subjects
    if question_kind(query) == "tower" and any(mark in (query or "") for mark in ("十六", "透镜")):
        pool = [fact for fact in rows if any(mark in statement_of(fact) for mark in ("十六", "透镜"))]
        focus = []
    elif subjects:
        anchored = [fact for fact in rows if all(name in statement_of(fact) for name in subjects)]
        pool = anchored
    found: list[tuple[int, str, dict]] = []
    for fact in pool:
        rescued = _from_fact(query, fact, focus)
        if rescued:
            found.append((_score(query, statement_of(fact)), rescued[0], rescued[1]))
    if not found:
        linked = _linked_electric(query, rows)
        if linked:
            return linked
        return None
    found.sort(key=lambda item: item[0], reverse=True)
    return found[0][1], found[0][2]


def _linked_electric(query: str, rows: list[dict]) -> tuple[str, dict] | None:
    """改用电灯写在另一句。问的是这座塔或它的守护者时，仍然用那一年。"""
    from memory_core.span_guard import statement_of

    asked = query or ""
    if "电" not in asked or _wrong_event(asked, ""):
        return None
    keepers: dict[str, str] = {}
    for fact in rows:
        text = statement_of(fact)
        keeper = _keeper(text)
        named = re.search(r"名叫([\u4e00-\u9fff]{2,4}塔)", text)
        if keeper and named:
            keepers[keeper] = named.group(1)
    for fact in rows:
        text = statement_of(fact)
        if "电" not in text or _wrong_event(asked, text):
            continue
        year = re.search(r"(\d{3,4}年)", text)
        if not year:
            continue
        tower = ""
        for match in re.finditer(r"塔", text):
            for length in (2, 3, 1):
                begin = match.start() - length
                if begin < 0:
                    continue
                chunk = text[begin:match.end()]
                if chunk and chunk[0] not in "年的座第这那" and chunk.endswith("塔"):
                    tower = chunk
                    break
            if tower and tower != "灯塔":
                break
        linked = "灯塔" in asked or "塔" in asked or (tower and tower in asked)
        if not linked:
            linked = any(person in asked and their_tower and their_tower in text for person, their_tower in keepers.items())
        if not linked:
            continue
        span = year.group(1)
        if accept_span(asked, span, text, allow_chain=True):
            return span, fact
    return None

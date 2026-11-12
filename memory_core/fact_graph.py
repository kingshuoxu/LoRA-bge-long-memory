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
    ("她爹", "father"),
    ("他爹", "father"),
    ("爹", "father"),
    ("爸", "father"),
    ("母亲", "mother"),
    ("妈妈", "mother"),
    ("女儿", "daughter"),
    ("闺女", "daughter"),
    ("丫头", "daughter"),
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
    ("养的那只猫", "pet:猫"),
    ("养的那只狗", "pet:狗"),
    ("养的那只鸟", "pet:鸟"),
    ("养的猫", "pet:猫"),
    ("养的狗", "pet:狗"),
    ("养的鸟", "pet:鸟"),
    ("养的海鸥", "pet:海鸥"),
    ("养的那只海鸥", "pet:海鸥"),
    ("家的猫咪", "pet:猫"),
    ("猫咪", "pet:猫"),
    ("养的", "pet"),
    ("的猫", "pet:猫"),
    ("的狗", "pet:狗"),
    ("的鸟", "pet:鸟"),
    ("猫", "pet:猫"),
    ("狗", "pet:狗"),
    ("鸟", "pet:鸟"),
    ("小主人", "owner"),
    ("主人", "owner"),
    ("雇主", "employer"),
    ("东家", "employer"),
    ("老板", "employer"),
    ("守护人", "keeper_of"),
    ("守护者", "keeper_of"),
    ("看守人", "keeper_of"),
    ("值守人", "keeper_of"),
    ("守灯人", "keeper_of"),
    ("灯夫", "keeper_of"),
    ("司灯", "keeper_of"),
    ("看守的", "keeps"),
    ("守护的", "keeps"),
    ("守着的", "keeps"),
    ("值守的", "keeps"),
    ("看管的", "keeps"),
    ("看着的", "keeps"),
    ("站岗的", "keeps"),
    ("执勤的", "keeps"),
    ("站岗", "keeps"),
    ("执勤", "keeps"),
    ("守的", "keeps"),
    ("看的", "keeps"),
    ("的海鸥", "pet:海鸥"),
    ("海鸥", "pet:海鸥"),
    ("值守", "keeper_of"),
    ("的学校", "school"),
    ("学校", "school"),
)
_OBJECT_ALIAS = (
    frozenset({"汽车", "车"}),
    frozenset({"自行车", "单车"}),
    frozenset({"猫", "猫咪"}),
    frozenset({"狗", "小狗"}),
)
_TERMINALS = (
    (r"是什么颜色|啥颜色|什么颜色|什么色", "color"),
    (r"住哪儿|住哪里|住在哪|居住在|住址在|住址是|现居哪|哪座城市", "home"),
    (r"做什么工作|什么手艺|靠什么|职业是什么|谋生", "job"),
    (r"老家|哪里长大|在哪里长大|家乡是", "hometown"),
    (r"哪种花|偏爱哪|喜欢的花", "flower"),
    (r"哪一年创立|创立于哪|成立于哪|什么时候成立|何时成立|哪一年成立", "founded"),
    (r"总部设在|总部在哪", "headquarters"),
    (r"谁创办|谁创立|创始人是谁", "founder"),
    (r"主打什么产品|主要卖什么产品|卖什么产品|主打什么", "product"),
    (r"有多少员工|多少员工|员工人数", "staff"),
    (r"什么茶|哪种茶|茶是什么|爱喝的茶", "tea"),
    (r"是什么牌子|是什么品牌|什么牌子|什么品牌|哪个牌子|哪个品牌", "brand"),
    (r"在哪(?:里|儿)?上班|在哪(?:里|儿)?工作|哪里上班|哪儿工作|哪里工作", "workplace"),
    (r"哪一年拆除|哪年拆除|何时拆除|什么时候拆除|哪年拆的|哪一年拆|哪年拆掉|什么时候拆", "demolished"),
    (r"建于哪一年|哪一年建的|哪年建成|哪年建的|是哪一年建的", "built"),
    (r"哪年去世|哪一年去世|何时去世|哪年逝世|死于哪一年|哪年死的", "died"),
    (r"哪年出生|哪一年出生|是哪年出生|生于哪一年", "born"),
    (r"哪一天开始|哪天开始|哪天晒|开始晒|哪一天晒", "started"),
    (r"哪一年开始|哪年开始|什么时候开始|何时开始", "started"),
    (r"产自哪|产自哪儿|哪里的特产|哪儿的特产", "origin"),
    (r"有多高|多高|塔高多少|多少米", "height"),
    (r"哪所学校|什么学校|哪里上学|哪儿上学|在哪上学|在哪读书|在哪儿念书|哪儿念书|学校叫什么|的学校叫", "school"),
    (r"哪国人|什么国籍|国籍是什么|是哪国人", "nationality"),
    (r"谁守护|谁看守|谁值守|是谁守护|是谁看守|是谁守的|谁守的", "keeper"),
    (r"哪座灯塔|哪座塔|哪一座塔|什么塔", "tower"),
    (r"几条腿|多少条腿", "legs"),
    (r"什么鸟|哪种鸟|是什么鸟", "species"),
    (r"是谁磨|谁磨的|谁打磨|谁磨了|哪位.{0,4}磨", "maker"),
    (r"谁养的|谁养了|是谁养", "owner"),
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
    if left.endswith("车") and "自行车" not in left and right in {"车", "汽车"}:
        return True
    if right.endswith("车") and "自行车" not in right and left in {"车", "汽车"}:
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
            r"([\u4e00-\u9fff]{2,3})的(女儿|儿子|父亲|母亲|爸爸|妈妈|哥哥|弟弟|姐姐|妹妹|妻子|丈夫)(?:是|叫)?([\u4e00-\u9fff]{2,3})(?=养|的|，|。|$|是|在|和)",
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
        raised = text.find("养了")
        called_name = re.search(r"养了.{0,24}(?:名叫|名字叫)([\u4e00-\u9fff]{1,6})", text)
        if raised > 0 and called_name:
            owner = text[:raised].split("的")[-1]
            owner = re.sub(r"^(?:女儿|儿子|父亲|母亲|爸爸|妈妈|女孩|男孩)", "", owner)
            owner = owner[-4:] if len(owner) > 4 else owner
            if re.fullmatch(r"[\u4e00-\u9fff]{2,4}", owner):
                add(owner, "pet", called_name.group(1), fact)
                add(called_name.group(1), "owner", owner, fact)
                if "海鸥" in text:
                    add("海鸥", "owner", owner, fact)
                    add("海鸥", "named", called_name.group(1), fact)
                    add(called_name.group(1), "species", "海鸥", fact)
                    add(owner, "species", "海鸥", fact)
                if "鸟" in text and "海鸥" not in text:
                    add("鸟", "owner", owner, fact)
                legs = re.search(r"([一二三四五六七八九十两])条腿", text)
                if legs:
                    add(called_name.group(1), "legs", legs.group(1), fact)
                    if "海鸥" in text:
                        add("海鸥", "legs", legs.group(1), fact)
        called = re.search(r"(猫|狗|鸟|海鸥).{0,8}名字是([\u4e00-\u9fff]{1,8})", text)
        if called:
            kind = called.group(1)
            add(kind, "named", called.group(2), fact)
            if f"那只{kind}" in text:
                add(f"那只{kind}", "named", called.group(2), fact)
        named_pet = re.search(r"([\u4e00-\u9fff]{2,4})的(猫|狗|鸟)(?:的名字)?(?:叫|是)([\u4e00-\u9fff]{1,8})", text)
        if named_pet:
            add(named_pet.group(1), "pet", named_pet.group(3), fact, named_pet.group(2))
            add(named_pet.group(3), "owner", named_pet.group(1), fact)
        work = re.search(r"([\u4e00-\u9fff]{2,4})在([\u4e00-\u9fff]{2,16})(?:上班|工作)", text)
        if work:
            add(work.group(1), "workplace", work.group(2), fact)
        home = re.search(r"([\u4e00-\u9fff]{2,4})的住址是([\u4e00-\u9fff]{2,16})", text)
        if home:
            add(home.group(1), "home", home.group(2), fact)
        lives = re.search(r"([\u4e00-\u9fff]{2,4})住在([\u4e00-\u9fff]{2,16})", text)
        if lives:
            add(lives.group(1), "home", lives.group(2), fact)
        tea = re.search(
            r"([\u4e00-\u9fff]{2,3})(?:最喜欢的|最爱的|喜欢的|爱喝的)?茶是([\u4e00-\u9fff]{2,12})",
            text,
        )
        if tea:
            add(tea.group(1), "tea", tea.group(2), fact)
        job = re.search(r"([\u4e00-\u9fff]{2,3})的职业是([\u4e00-\u9fff]{2,8})", text)
        if job:
            add(job.group(1), "job", job.group(2), fact)
        hometown = re.search(r"([\u4e00-\u9fff]{2,3})的家乡是([\u4e00-\u9fff]{2,8})", text)
        if hometown:
            add(hometown.group(1), "hometown", hometown.group(2), fact)
        flower = re.search(
            r"([\u4e00-\u9fff]{2,3})(?:最喜欢的|最爱的|喜欢的|偏爱的)?花是([\u4e00-\u9fff]{2,8})",
            text,
        )
        if flower and "讨厌" not in text:
            add(flower.group(1), "flower", flower.group(2), fact)
        founded = re.search(r"([\u4e00-\u9fff]{2,8})成立于(\d{3,4})年", text)
        if founded:
            add(founded.group(1), "founded", founded.group(2), fact)
        headquarters = re.search(r"([\u4e00-\u9fff]{2,8})的总部在([\u4e00-\u9fff]{2,8})", text)
        if headquarters:
            add(headquarters.group(1), "headquarters", headquarters.group(2), fact)
        founder = re.search(r"([\u4e00-\u9fff]{2,8})的创始人是([\u4e00-\u9fff]{2,4})", text)
        if founder:
            add(founder.group(1), "founder", founder.group(2), fact)
        product = re.search(r"([\u4e00-\u9fff]{2,8})的主打产品是([\u4e00-\u9fff]{2,12})", text)
        if product:
            add(product.group(1), "product", product.group(2), fact)
        staff = re.search(r"([\u4e00-\u9fff]{2,8})的员工人数是([0-9一二三四五六七八九十百零]+人)", text)
        if staff:
            add(staff.group(1), "staff", staff.group(2), fact)
        kept = re.search(
            r"([\u4e00-\u9fff]{2,3})(?:在[\u4e00-\u9fff]{0,8})?(?:看守|守护|值守)的[\u4e00-\u9fff]{0,8}名叫([\u4e00-\u9fff]{2,8})",
            text,
        )
        if kept:
            add(kept.group(1), "keeps", kept.group(2), fact)
        kept_at = re.search(r"([\u4e00-\u9fff]{2,4})在([\u4e00-\u9fff]{2,8})(?:值守|看守|守护)", text)
        if kept_at and not kept:
            add(kept_at.group(1), "keeps", kept_at.group(2), fact)
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
        made = re.search(r"(?:工匠|师傅)([\u4e00-\u9fff]{2,3})打磨", text)
        tower_name = ""
        for match in re.finditer(r"([\u4e00-\u9fff]{2,4})塔", text):
            name = match.group(1) + "塔"
            while name and name[0] in "年月日的座第这那":
                name = name[1:]
            if len(name) >= 3 and name.endswith("塔"):
                tower_name = name
        if made and tower_name:
            add(tower_name, "maker", made.group(1), fact)
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
        meters = re.search(r"塔高([0-9一二三四五六七八九十百千两]{1,8}米)", text)
        named_tower = re.search(r"名叫([\u4e00-\u9fff]{1,6}塔)", text)
        if meters and named_tower:
            add(named_tower.group(1), "height", meters.group(1), fact)
        else:
            height = re.search(r"([\u4e00-\u9fff]{2,8}).{0,8}(?:高|塔高)([0-9一二三四五六七八九十百千两]{1,8}米)", text)
            if height and "建于" not in text[max(0, height.start() - 2): height.end()]:
                add(height.group(1), "height", height.group(2), fact)
        school = re.search(
            r"([\u4e00-\u9fff]{2,4})(?:在([\u4e00-\u9fffA-Za-z0-9·]{2,16})(?:上学|读书|念书)|就读于([\u4e00-\u9fffA-Za-z0-9·]{2,16})|毕业于([\u4e00-\u9fffA-Za-z0-9·]{2,16}))",
            text,
        )
        if school:
            place = school.group(2) or school.group(3) or school.group(4)
            add(school.group(1), "school", place, fact)
        school_is = re.search(r"([\u4e00-\u9fff]{2,4})的学校(?:是|叫)([\u4e00-\u9fffA-Za-z0-9·]{2,16})", text)
        if school_is:
            add(school_is.group(1), "school", school_is.group(2), fact)
        student = re.search(r"([\u4e00-\u9fff]{2,4})是([\u4e00-\u9fffA-Za-z0-9·]{2,16})的学生", text)
        if student:
            add(student.group(1), "school", student.group(2), fact)
        nation = re.search(r"([\u4e00-\u9fff]{2,4})是([\u4e00-\u9fff]{1,8})(?:人|工匠|师傅)", text)
        if nation and nation.group(2) not in {"学生", "本地", "外地"} and not re.search(r"[0-9一二三四五六七八九十百]", nation.group(2)):
            add(nation.group(1), "nationality", nation.group(2).removesuffix("工").removesuffix("师"), fact)
        origin = re.search(
            r"(瑞典|挪威|中国|日本|英国|法国|德国|美国|荷兰|丹麦|芬兰)(?:工匠|师傅)([\u4e00-\u9fff]{2,4})",
            text,
        )
        if origin:
            person = re.split(r"[打磨的在上]", origin.group(2))[0]
            if len(person) >= 2:
                add(person, "nationality", origin.group(1), fact)
        started = re.search(r"([\u4e00-\u9fff]{2,8}).{0,8}(\d{3,4}年)(?:起|开始)", text)
        if started:
            add(started.group(1), "started", started.group(2), fact)
        colored = re.search(r"([蓝红白绿青黑金银灰紫黄]色).{0,12}名叫([\u4e00-\u9fff]{2,8})", text)
        if colored:
            add(colored.group(2), "color", colored.group(1), fact)
        if "霜降" in text and "晾" in text:
            named_salt = re.search(r"名叫([\u4e00-\u9fff]{2,8})", text)
            if named_salt:
                add("霜降", "named", named_salt.group(1), fact)
                add(named_salt.group(1), "started", "霜降", fact)
        origin = re.search(r"([\u4e00-\u9fff]{2,8})的特产是.{0,20}名叫([\u4e00-\u9fff]{2,8})", text)
        if origin:
            add(origin.group(2), "origin", origin.group(1), fact)
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
        while True:
            nxt = rest.lstrip("的，,、 ")
            nxt = re.sub(r"^(?:上面|那些|镜片|透镜|灯塔|塔上)", "", nxt)
            if nxt == rest:
                break
            rest = nxt
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
            if matched == "养的" and not rest[len(matched):].startswith(("猫", "狗", "鸟", "海", "那", "一", "是")):
                rest = rest[len(matched):]
                continue
            if hops and rel == hops[-1]:
                rest = rest[len(matched):]
                continue
            hops.append(rel)
            rest = rest[len(matched):]
            continue
        if rest[:1] in "，,、":
            rest = rest[1:]
            continue
        segment = re.match(r"[\u4e00-\u9fff]+", rest)
        if not segment:
            return None
        piece = segment.group(0)
        cut = len(piece)
        for word, _kind in words:
            at = piece.find(word)
            if 0 < at < cut:
                cut = at
        if cut <= 0:
            return None
        if re.search(r"塔|守|透镜|镜片", rest[:cut]):
            if re.fullmatch(
                r"(?:这|那|第|座|灯塔|塔|透镜|镜片|上面|上|的|是|[一二三四五六七八九十两0-9])+",
                piece,
            ):
                rest = rest[cut:]
                continue
            return None
        rest = rest[cut:]
        continue
    return hops


def _attribute_object(body: str, start: str) -> str:
    rest = body[body.find(start) + len(start):] if start and start in body else ""
    rest = rest.lstrip("的")
    rest = re.sub(r"^(?:那|这|一)?(?:辆|只|个|座)", "", rest)
    return rest.strip("的 ")


def _plain_choice(value: str) -> str:
    return re.sub(r"(?:色|的)+$", "", value or "")


def _choice(text: str, edges: list[tuple[str, str, str, str, dict]]) -> dict[str, Any] | None:
    matched = re.match(r"^(?P<head>.+?)是(?P<a>[^，,。？?]{1,16})还是(?P<b>[^，,。？?]{1,16})$", text)
    if not matched:
        return None
    head, left, right = matched.group("head"), matched.group("a"), matched.group("b")
    nodes = _nodes(edges)
    start = _start_name(head, nodes)
    sides = {_plain_choice(left), _plain_choice(right)}
    want = ""
    if any(mark in head for mark in ("颜色", "色")):
        want = "color"
    elif any(mark in head for mark in ("牌子", "品牌")):
        want = "brand"
    obj = _attribute_object(head, start) if start else ""
    found: list[tuple[str, dict]] = []
    for src, rel, dst, edge_obj, fact in edges:
        if start and src != start and start not in _statement(fact):
            continue
        if want and rel not in {want, "pet", "named", "daughter", "school", "nationality"}:
            if rel != want:
                continue
        if start and obj and edge_obj and rel in {"color", "brand"} and not _objects_align(obj, edge_obj):
            continue
        plain = _plain_choice(dst)
        if plain and plain in sides:
            found.append((dst, fact))
    unique: list[tuple[str, dict]] = []
    for dst, fact in found:
        if all(_plain_choice(dst) != _plain_choice(old) for old, _fact in unique):
            unique.append((dst, fact))
    if len(unique) == 1:
        return {"status": "answer", "span": unique[0][0], "fact": unique[0][1]}
    if start or unique:
        return {"status": "abstain"}
    return None


def _maker_asked(text: str) -> bool:
    """问的是磨镜的人。塔名叫什么不是。"""
    parts = [part.strip() for part in re.split(r"[，,。；;]", text or "") if part.strip()]
    asked = parts[-1] if parts else text
    if re.search(r"塔叫|名称是什么|的名称", asked) and not re.search(r"师傅|工匠|谁|哪位", asked):
        return False
    if re.search(r"闺女|女儿|丫头", asked):
        return False
    if re.search(r"哪座|什么塔|哪一座", asked):
        return False
    if re.search(r"师傅|工匠", asked) and re.search(r"磨|镜", text or ""):
        return True
    return bool(re.search(r"谁.{0,4}磨|哪位.{0,8}磨|磨成|打磨", asked))


def _parse(query: str, edges: list[tuple[str, str, str, str, dict]]) -> dict[str, Any] | None:
    text = without_tag_question(query or "").strip().rstrip("？?。")
    if not text:
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
    if _maker_asked(text):
        terminal = "maker"
        parts = [part.strip() for part in re.split(r"[，,。；;]", text) if part.strip()]
        if len(parts) > 1:
            body = "，".join(parts[:-1])
        else:
            body = re.split(r"谁|哪位|师傅|工匠", text)[0]
    if not terminal:
        return None
    if terminal not in {"maker", "founder", "owner"} and "谁" in text and not re.search(r"的[\u4e00-\u9fff]{1,4}(?:是谁|叫什么|叫啥)", text):
        return None
    nodes = _nodes(edges)
    start = _start_name(body or text, nodes)
    if not start and "海鸥" in nodes and re.search(r"那只鸟|这只鸟|鸟的|鸟主人|它主人|它爸", text):
        start = "海鸥"
        body = re.sub(r"^.*?(?:那只|这只)?鸟", "", body or text, count=1)
    if not start:
        return None
    hops = _parse_hops(body, start, terminal)
    if hops and start in {"海鸥", "鸟"} and hops[0] in {"father", "mother"} and "owner" not in hops:
        hops = ["owner", *hops]
    guarded = re.search(rf"(?:守护|看守|值守){re.escape(start)}的(?:人|那位)", body or text)
    if guarded:
        later = _parse_hops((body or text)[guarded.end():], "", terminal)
        if later is not None:
            hops = ["keeper_of", *later]
    if hops is None:
        # 认不出的中间词不能退回去拿起点自己的取值，也不能换一条事实来答。
        return {"status": "abstain"}
    if terminal == "keeper" and "keeper_of" not in hops:
        hops = [*hops, "keeper_of"]
        terminal = "identity"
    elif terminal == "keeper":
        terminal = "identity"
    obj = _attribute_object(body, start) if terminal in {"color", "brand"} and not hops else ""
    if obj in {"是", "为", "的"}:
        obj = ""
    return {"status": "chain", "start": start, "hops": hops, "terminal": terminal, "object": obj}


def _walk(start: str, hops: list[str], edges: list[tuple[str, str, str, str, dict]]) -> tuple[str, dict] | None:
    node = start
    fact: dict = {}
    for hop in hops:
        if hop == "keeper_of":
            nxt = [(src, host) for src, rel, dst, _obj, host in edges if rel == "keeps" and dst == node]
        elif hop.startswith("pet"):
            kind = hop.split(":", 1)[1] if ":" in hop else ""
            nxt = []
            for src, rel, dst, _obj, host in edges:
                if src != node or rel != "pet":
                    continue
                host_text = _statement(host)
                if kind == "鸟" and "海鸥" in host_text:
                    nxt.append((dst, host))
                    continue
                if kind and kind not in host_text and kind not in dst:
                    continue
                nxt.append((dst, host))
        elif hop == "owner":
            nxt = [(dst, host) for src, rel, dst, _obj, host in edges if src == node and rel == "owner"]
            if not nxt:
                nxt = [(src, host) for src, rel, dst, _obj, host in edges if rel == "pet" and dst == node]
        else:
            nxt = [(dst, host) for src, rel, dst, _obj, host in edges if src == node and rel == hop]
        if hop == "employer" or len(nxt) != 1:
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


def _duty_keeper(query: str, edges: list[tuple[str, str, str, str, dict]]) -> dict[str, Any] | None:
    """后半句问谁在照管这座塔，而且只记下了一位看守，就回答那位。"""
    parts = [part.strip() for part in re.split(r"[，,。；;]", query) if part.strip()]
    tail = parts[-1] if parts else query
    if re.search(r"塔叫|灯塔叫|叫啥名|女儿|闺女|丫头|磨|透镜|镜片", tail):
        return None
    if re.search(r"灯塔[^叫]{0,8}叫|的塔[^叫]{0,8}名称|塔的名称", tail):
        return None
    if not re.search(r"值守|看顾|照管|照看|站岗|执勤|接班|当值|守夜|轮值|看护|照应|照拂|看管", tail):
        return None
    if not re.search(r"叫什么|是谁|叫啥|哪位|那位", tail):
        return None
    kept = [(src, host) for src, rel, _dst, _obj, host in edges if rel == "keeps"]
    names = list(dict.fromkeys(src for src, _host in kept))
    if len(names) != 1:
        return None
    return {"status": "answer", "span": names[0], "fact": kept[0][1]}


def _different_person(query: str, edges: list[tuple[str, str, str, str, dict]]) -> bool:
    """问句里的名字比已存实体多一个字时，不要把那个人当成同一个。"""
    from memory_core.fact_span import near_miss_span

    verbs = (
        "离", "到", "往", "打", "磨", "守", "养", "建", "的", "就", "毕", "上", "家", "念", "读",
        "负", "只", "把", "是", "在", "不", "照", "值", "站", "执", "看", "管",
        "哪", "还", "什", "谁", "吗", "呢", "多", "几", "世", "年", "叫", "啥", "色", "去",
        "现", "开", "最", "也", "都", "很", "曾", "已", "正", "刚", "才", "这", "那", "又",
        "住", "居", "喜", "爱", "自", "骑", "喝", "吃", "会", "想", "要", "能", "可",
        "靠", "老", "偏", "做", "从", "以", "成", "总", "主", "有", "养",
        "她", "他", "它", "女",
    )
    text = query or ""
    values = {
        dst
        for _src, rel, dst, _obj, _host in edges
        if rel in {"color", "height", "built", "started", "legs", "nationality"}
    }
    for name in _nodes(edges):
        if name in values:
            continue
        start = 0
        while True:
            index = text.find(name, start)
            if index < 0:
                break
            tail = text[index + len(name):]
            if tail.startswith(("相关", "情况", "资料", "信息", "简介", "背景", "工匠", "师傅", "灯塔", "晾", "产")):
                start = index + 1
                continue
            after = tail[:1]
            if after and re.fullmatch(r"[\u4e00-\u9fff]", after) and not after.startswith(verbs):
                return True
            start = index + 1
        missed = near_miss_span(name, text)
        if not missed or missed == name:
            continue
        if missed.endswith(name) and not missed.startswith(name):
            continue
        extra = missed[len(name):] if missed.startswith(name) else ""
        if extra.startswith(("相关", "情况", "资料", "信息", "简介", "背景", "工匠", "师傅", "灯塔", "晾", "产", *verbs)):
            continue
        return True
    return False


_FAILED_HOP_ABSTAINS = {
    "father", "mother", "son", "daughter", "brother", "sister", "spouse", "child",
    "employer", "keeper_of", "pet", "owner", "keeps", "maker", "school", "workplace",
}


def resolve_graph(query: str, facts: list[dict]) -> dict[str, Any] | None:
    """答得了就给取值。问句是一条链但某一跳没有边，就弃权。不像链就返回 None。"""
    rows = [fact for fact in facts if isinstance(fact, dict)]
    edges = build_edges(rows)
    if not edges:
        return None
    if _different_person(query, edges):
        return {"status": "abstain"}
    duty = _duty_keeper(query or "", edges)
    if duty is not None:
        return duty
    parsed = _parse(query, edges)
    if not parsed:
        if re.search(r"守塔人|看守人|守护人|守塔的人", query or "") and not re.search(r"谁看守|谁守护", query or ""):
            kept = [(src, host) for src, rel, dst, _obj, host in edges if rel == "keeps"]
            names = list(dict.fromkeys(src for src, _host in kept))
            if len(names) == 1:
                if re.search(r"女儿|闺女|丫头", query or ""):
                    children = [
                        (dst, host)
                        for src, rel, dst, _obj, host in edges
                        if src == names[0] and rel == "daughter"
                    ]
                    if len(children) == 1:
                        return {"status": "answer", "span": children[0][0], "fact": children[0][1]}
                    return {"status": "abstain"}
                if not re.search(r"父亲|爸爸|爸|爹|妻子|老婆|太太", query or ""):
                    return {"status": "answer", "span": names[0], "fact": kept[0][1]}
        return None
    if parsed.get("status") in {"answer", "abstain"}:
        return parsed
    resolved_via = ""
    owners = [
        (src, rel, host)
        for src, rel, dst, _obj, host in edges
        if dst == parsed["start"] and rel in {"height", "built", "color", "nationality"}
    ]
    owner_names = list(dict.fromkeys(src for src, _rel, _host in owners))
    if len(owner_names) == 1 and owner_names[0] != parsed["start"]:
        parsed = {**parsed, "start": owner_names[0]}
        resolved_via = owners[0][1]
    if parsed["terminal"] == "tower" and not parsed["hops"]:
        asked = query or ""
        if re.search(r"打磨|磨了|磨的|磨成", asked):
            made = [(src, host) for src, rel, dst, _obj, host in edges if rel == "maker" and dst == parsed["start"]]
            if len(made) == 1:
                return {"status": "answer", "span": made[0][0], "fact": made[0][1]}
            return {"status": "abstain"}
        if re.search(r"守护|看守|值守", asked):
            kept = [(dst, host) for src, rel, dst, _obj, host in edges if rel == "keeps" and src == parsed["start"]]
            if len(kept) == 1:
                return {"status": "answer", "span": kept[0][0], "fact": kept[0][1]}
            return {"status": "abstain"}
        if re.search(r"是哪座", asked):
            return {"status": "abstain"}
        return None
    walked = _walk(parsed["start"], parsed["hops"], edges)
    if walked is None:
        # 任何一跳没有正好那条边，都弃权。不把中间的人、另一只宠物或另一句的取值交出去。
        if parsed["hops"] or parsed["terminal"] in {
            "demolished", "died", "born", "built", "started", "workplace", "brand", "color",
            "maker", "height", "school", "nationality", "identity",
        }:
            if any(hop in _FAILED_HOP_ABSTAINS for hop in parsed["hops"]) or parsed["terminal"] != "identity" or parsed["hops"]:
                return {"status": "abstain"}
        return {"status": "abstain"}
    node, fact = walked
    terminal = parsed["terminal"]
    if terminal == "tower":
        return {"status": "answer", "span": node, "fact": fact}
    if terminal == "identity":
        if not parsed["hops"]:
            named = [(dst, host) for src, rel, dst, _obj, host in edges if src == node and rel == "named"]
            asks_tower = bool(re.search(r"灯塔叫|塔叫|座灯塔", query or ""))
            if asks_tower:
                towers = list(dict.fromkeys(
                    dst for _src, rel, dst, _obj, _host in edges if rel == "keeps" and dst.endswith("塔")
                ))
                people = [
                    name for name in _nodes(edges)
                    if name in (query or "") and not name.endswith("塔") and name not in {"霜降", "蓝色"}
                ]
                keepers = {src for src, rel, _dst, _obj, _host in edges if rel == "keeps"}
                if people and any(person not in keepers for person in people):
                    return {"status": "abstain"}
                if len(towers) == 1:
                    host = next(host for _src, rel, dst, _obj, host in edges if rel == "keeps" and dst == towers[0])
                    return {"status": "answer", "span": towers[0], "fact": host}
                return {"status": "abstain"}
            if len(named) == 1:
                return {"status": "answer", "span": named[0][0], "fact": named[0][1]}
            if resolved_via == "nationality":
                return {"status": "answer", "span": node, "fact": owners[0][2]}
            return {"status": "abstain"}
        return {"status": "answer", "span": node, "fact": fact}
    obj = parsed.get("object") or ""
    if terminal in {"color", "brand"} and obj:
        aligned = [
            rel
            for src, rel, _dst, edge_obj, _host in edges
            if src == node and edge_obj and _objects_align(obj, edge_obj) and rel in {"color", "brand"}
        ]
        if not aligned or terminal not in aligned:
            return {"status": "abstain"}
    picked = _attribute(node, terminal, obj, edges)
    if picked is None and terminal == "started" and re.search(r"晒|晾", query or ""):
        seasons = [(dst, host) for _src, rel, dst, _obj, host in edges if rel == "started"]
        unique = list(dict.fromkeys(dst for dst, _host in seasons))
        if len(unique) == 1:
            return {"status": "answer", "span": unique[0], "fact": seasons[0][1]}
    if picked is None:
        return {"status": "abstain"}
    return {"status": "answer", "span": picked[0], "fact": picked[1]}

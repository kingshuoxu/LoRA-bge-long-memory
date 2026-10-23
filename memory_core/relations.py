"""问句和事实是不是同一种关系。

只看语言里的关系，不看某个人或某家公司的专名。
老家和住址是两种关系；「for a living」是职业，不因为里面有 living 就算住址。
问句点明了一种关系、记忆里没有同一种时，调用方应拒答，而不是拿另一条事实来答。
"""
from __future__ import annotations

import re

from memory_core.prompts import has_cjk

# 问句点了这些关系、事实对不上时必须拒答。
RESTRICTIVE = frozenset({
    "residence",
    "origin",
    "occupation",
    "age",
    "contact",
    "dislike",
    "like",
    "founding",
    "headquarters",
    "founder",
    "instrument",
    "name",
    "color",
    "headcount",
    "product",
    "height",
})


def _en(text: str) -> str:
    return (text or "").casefold()


def _relations(text: str) -> set[str]:
    raw = text or ""
    if has_cjk(raw):
        found: set[str] = set()
        if any(mark in raw for mark in ("讨厌", "最恨", "不喜欢")):
            found.add("dislike")
        elif any(mark in raw for mark in ("最喜欢", "最爱", "偏爱", "喜欢")):
            found.add("like")
        if any(mark in raw for mark in ("几岁", "多少岁", "年龄", "多大")):
            found.add("age")
        if "多高" in raw or "身高" in raw:
            found.add("height")
        if any(mark in raw for mark in ("电话", "手机", "邮箱", "邮件")):
            found.add("contact")
        if any(mark in raw for mark in ("老家", "家乡", "长大", "籍贯", "出生")):
            found.add("origin")
        elif any(mark in raw for mark in ("现居", "居住", "住址", "住在", "家在", "住哪", "住哪儿")):
            found.add("residence")
        elif "住" in raw and "记住" not in raw:
            found.add("residence")
        if any(mark in raw for mark in ("职业", "工作", "谋生", "手艺", "做什么")):
            found.add("occupation")
        if any(mark in raw for mark in ("成立", "创立", "创办于", "成立于")):
            found.add("founding")
        if "总部" in raw:
            found.add("headquarters")
        if any(mark in raw for mark in ("创始人", "创办人", "谁创办", "谁创立", "谁成立")):
            found.add("founder")
        if any(mark in raw for mark in ("乐器", "弹", "演奏")):
            found.add("instrument")
        if any(mark in raw for mark in ("名字", "叫什么", "叫啥", "是叫")):
            found.add("name")
        if any(mark in raw for mark in ("颜色", "什么色", "啥色")):
            found.add("color")
        if any(mark in raw for mark in ("员工", "多少人", "人数", "几个人")):
            found.add("headcount")
        if any(mark in raw for mark in ("产品", "旗舰")):
            found.add("product")
        # 「柏若岚是医生吗」没有写出职业，但是一个没有事物名的系词问句。
        # 带「的」的是事物取值（车是墨绿色的吗），不在这里当成职业。
        if not found:
            bare = raw.strip().rstrip("？?")
            copula = re.match(r"^([\u4e00-\u9fff]{2,12})是([\u4e00-\u9fff]{1,8})吗$", bare)
            if copula and "的" not in copula.group(1) and "的" not in copula.group(2):
                found.add("occupation")
        return found

    low = _en(raw)
    found = set()
    if re.search(r"\b(hate|hates|dislike|dislikes|least favorite|least favourite)\b", low):
        found.add("dislike")
    elif re.search(r"\b(favorite|favourite|prefer|likes)\b", low):
        found.add("like")
    if re.search(r"\bhow old\b", low) or re.search(r"\bage\b", low):
        found.add("age")
    if re.search(r"\bhow tall\b", low) or re.search(r"\bheight\b", low):
        found.add("height")
    if re.search(r"\b(e-?mail|phone|telephone)\b", low):
        found.add("contact")
    if re.search(r"\b(hometown|home town|originally|grew up|grow up|born)\b", low):
        found.add("origin")
    living_job = bool(re.search(r"\bfor a living\b", low))
    if living_job or re.search(r"\b(occupation|profession|career)\b", low) or re.search(r"\bjobs?\b", low):
        found.add("occupation")
    elif re.search(r"\b(works? as|working as)\b", low):
        found.add("occupation")
    elif re.search(r"\bwhat does\b", low) and re.search(r"\bdo\b", low):
        found.add("occupation")
    if "origin" not in found and "occupation" not in found:
        if re.search(r"\b(lives?|lived|address|residing)\b", low) or re.search(r"\bliving in\b", low):
            found.add("residence")
    if re.search(r"\b(founded|established)\b", low):
        found.add("founding")
    elif re.search(r"\b(when|what year|which year)\b", low) and re.search(r"\b(start|started)\b", low):
        found.add("founding")
    if re.search(r"\b(headquarters|headquartered|based)\b", low):
        found.add("headquarters")
    if re.search(r"\b(founder|founded by|who started|who founded)\b", low):
        found.add("founder")
    if re.search(r"\b(instrument|play|plays|playing)\b", low):
        found.add("instrument")
    if re.search(r"\b(name|named|called)\b", low):
        found.add("name")
    if re.search(r"\bcolou?rs?\b", low):
        found.add("color")
    if re.search(r"\b(employees|employee|headcount|how many)\b", low):
        found.add("headcount")
    if re.search(r"\b(product|flagship)\b", low):
        found.add("product")
    return found


def query_relations(text: str) -> set[str]:
    return _relations(text) & RESTRICTIVE


def fact_relations(attr: str, statement: str = "") -> set[str]:
    return _relations(f"{attr or ''} {statement or ''}") & RESTRICTIVE


def shares_relation(query: str, attr: str, statement: str = "") -> bool:
    """问句没有点明关系时不拦截。点明了就必须和事实有交集。"""
    asked = query_relations(query)
    if not asked:
        return True
    return bool(asked & fact_relations(attr, statement))

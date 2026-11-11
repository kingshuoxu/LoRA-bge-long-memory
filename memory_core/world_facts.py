"""少量能核对的常识。查不到的专名直接说不知道，不交给基座编。"""
from __future__ import annotations

import re

_CAPITALS = {
    "法国": "巴黎",
    "中国": "北京",
    "日本": "东京",
    "英国": "伦敦",
    "德国": "柏林",
    "美国": "华盛顿",
    "意大利": "罗马",
    "俄罗斯": "莫斯科",
    "西班牙": "马德里",
    "加拿大": "渥太华",
    "澳大利亚": "堪培拉",
    "印度": "新德里",
    "韩国": "首尔",
    "巴西": "巴西利亚",
    "埃及": "开罗",
}

_STOP = {
    "什么", "哪里", "哪儿", "哪个", "哪些", "怎么", "如何", "是谁", "叫什么", "首都",
    "化学", "化学式", "等于", "多少", "几岁", "创始人", "老板", "牌子", "品牌", "颜色",
    "国籍", "哪里人", "哪儿人", "产地", "原产", "请问", "告诉", "知道", "一个", "这个",
    "那个", "什么牌子", "什么品牌",
}


def world_reply(text: str, known_names: list[str] | None = None) -> str | None:
    """首都给核对过的答案。记忆里没有的专名说不知道。其余交给基座。"""
    raw = (text or "").strip()
    if not raw:
        return None
    capital = re.search(r"([\u4e00-\u9fff]{2,8})的首都", raw)
    if capital:
        country = capital.group(1)
        if country in _CAPITALS:
            return _CAPITALS[country] + "。"
        return "我不知道。"
    if not re.search(r"是谁|叫什么|叫啥|什么牌子|什么品牌|创始人|老板是|哪里人|哪儿人|哪国人|产地|原产", raw):
        return None
    known = {name for name in (known_names or []) if name and len(name) >= 2}
    known.update(_CAPITALS)
    names = [
        token for token in re.findall(r"[\u4e00-\u9fff]{2,8}", raw)
        if token not in _STOP and token not in known and not any(token in country or country in token for country in _CAPITALS)
    ]
    if names:
        return "我不知道。"
    return None

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
    "墨西哥": "墨西哥城",
    "泰国": "曼谷",
    "越南": "河内",
    "新加坡": "新加坡",
    "马来西亚": "吉隆坡",
    "印度尼西亚": "雅加达",
    "菲律宾": "马尼拉",
    "土耳其": "安卡拉",
    "希腊": "雅典",
    "荷兰": "阿姆斯特丹",
    "瑞士": "伯尔尼",
    "瑞典": "斯德哥尔摩",
    "挪威": "奥斯陆",
    "丹麦": "哥本哈根",
    "芬兰": "赫尔辛基",
    "波兰": "华沙",
    "奥地利": "维也纳",
    "葡萄牙": "里斯本",
    "爱尔兰": "都柏林",
    "新西兰": "惠灵顿",
    "南非": "比勒陀利亚",
    "阿根廷": "布宜诺斯艾利斯",
    "智利": "圣地亚哥",
    "蒙古": "乌兰巴托",
    "朝鲜": "平壤",
    "乌克兰": "基辅",
    "匈牙利": "布达佩斯",
    "捷克": "布拉格",
    "冰岛": "雷克雅未克",
    "比利时": "布鲁塞尔",
    "卢森堡": "卢森堡",
    "摩纳哥": "摩纳哥",
    "马耳他": "瓦莱塔",
    "克罗地亚": "萨格勒布",
    "塞尔维亚": "贝尔格莱德",
    "罗马尼亚": "布加勒斯特",
    "保加利亚": "索非亚",
    "斯洛伐克": "布拉迪斯拉发",
    "斯洛文尼亚": "卢布尔雅那",
    "立陶宛": "维尔纽斯",
    "拉脱维亚": "里加",
    "爱沙尼亚": "塔林",
    "白俄罗斯": "明斯克",
    "哈萨克斯坦": "阿斯塔纳",
    "乌兹别克斯坦": "塔什干",
    "巴基斯坦": "伊斯兰堡",
    "孟加拉国": "达卡",
    "孟加拉": "达卡",
    "斯里兰卡": "科伦坡",
    "尼泊尔": "加德满都",
    "不丹": "廷布",
    "缅甸": "内比都",
    "柬埔寨": "金边",
    "老挝": "万象",
    "文莱": "斯里巴加湾市",
    "东帝汶": "帝力",
    "伊朗": "德黑兰",
    "伊拉克": "巴格达",
    "沙特阿拉伯": "利雅得",
    "沙特": "利雅得",
    "以色列": "耶路撒冷",
    "阿联酋": "阿布扎比",
    "卡塔尔": "多哈",
    "科威特": "科威特城",
    "约旦": "安曼",
    "黎巴嫩": "贝鲁特",
    "叙利亚": "大马士革",
    "也门": "萨那",
    "阿曼": "马斯喀特",
    "巴林": "麦纳麦",
    "阿富汗": "喀布尔",
    "塞浦路斯": "尼科西亚",
    "格鲁吉亚": "第比利斯",
    "亚美尼亚": "埃里温",
    "阿塞拜疆": "巴库",
    "尼日利亚": "阿布贾",
    "肯尼亚": "内罗毕",
    "埃塞俄比亚": "亚的斯亚贝巴",
    "摩洛哥": "拉巴特",
    "阿尔及利亚": "阿尔及尔",
    "突尼斯": "突尼斯",
    "加纳": "阿克拉",
    "坦桑尼亚": "多多马",
    "利比亚": "的黎波里",
    "苏丹": "喀土穆",
    "安哥拉": "罗安达",
    "秘鲁": "利马",
    "哥伦比亚": "波哥大",
    "委内瑞拉": "加拉加斯",
    "厄瓜多尔": "基多",
    "玻利维亚": "拉巴斯",
    "乌拉圭": "蒙得维的亚",
    "巴拉圭": "亚松森",
    "古巴": "哈瓦那",
    "巴拿马": "巴拿马城",
    "哥斯达黎加": "圣何塞",
}

# 核对过的二选一。不把没核对的一边交给基座猜。
_CHECKED_SIDES = {
    "月亮": "卫星",
    "月球": "卫星",
    "地球": "行星",
    "太阳": "恒星",
}

_STOP = {
    "什么", "哪里", "哪儿", "哪个", "哪些", "怎么", "如何", "是谁", "叫什么", "首都",
    "化学", "化学式", "等于", "多少", "几岁", "创始人", "老板", "牌子", "品牌", "颜色",
    "国籍", "哪里人", "哪儿人", "产地", "原产", "请问", "告诉", "知道", "一个", "这个",
    "那个", "什么牌子", "什么品牌",
}


def _capital_of(text: str) -> str:
    for country in sorted(_CAPITALS, key=len, reverse=True):
        if country in text and "首都" in text:
            return _CAPITALS[country]
    matched = re.search(r"([\u4e00-\u9fff]{2,8})的?首都", text)
    if not matched:
        return ""
    country = matched.group(1)
    if country in _CAPITALS:
        return _CAPITALS[country]
    if "首都" in text:
        return "我不知道"
    return ""


_COMMON_NAMES = {
    "熊猫", "猫", "狗", "水", "月亮", "月球", "太阳", "地球", "人", "动物", "鸟", "鱼",
    "马", "牛", "老虎", "狮子", "大象", "茶", "盐", "金", "银", "铁", "木头", "石头",
}


def stray_proper_names(text: str, known_names: list[str] | None = None) -> list[str]:
    """问句里的专名。国家、首都和普通事物不算。"""
    raw = text or ""
    known = {name for name in (known_names or []) if name and len(name) >= 2}
    known.update(_CAPITALS)
    known.update(_CHECKED_SIDES)
    known.update(_COMMON_NAMES)
    known.update(_STOP)
    return [
        token for token in re.findall(r"[\u4e00-\u9fff]{2,8}", raw)
        if token not in known and not any(token in country or country in token for country in _CAPITALS)
    ]


def world_reply(text: str, known_names: list[str] | None = None) -> str | None:
    """首都和核对过的二选一给答案。记忆里没有的专名说不知道。其余交给基座。"""
    raw = (text or "").strip()
    if not raw:
        return None
    capital = _capital_of(raw)
    if capital == "我不知道":
        return "我不知道。"
    if capital:
        choice = re.search(r"是(.+?)还是(.+?)(?:[？?。]|$)", raw)
        if choice:
            sides = (choice.group(1).strip(), choice.group(2).strip("？?。 "))
            for side in sides:
                if capital in side or side in capital:
                    return side if side.endswith("。") else side + "。"
            return "我不知道。"
        return capital + "。"
    for name, side in _CHECKED_SIDES.items():
        if name in raw and "还是" in raw and side in raw:
            return side + "。"
    known = [name for name in (known_names or []) if name and len(name) >= 2]
    if re.search(r"是.+还是", raw) and not any(name in raw for name in known):
        return "我不知道。"
    if re.search(r"干什么|做什么|是什么人|什么身份|什么物种|什么品种|什么动物|哪种动物|哪国人|哪里人|哪儿人", raw):
        if stray_proper_names(raw, known_names):
            return "我不知道。"
    if not re.search(
        r"是谁|叫什么|叫啥|什么牌子|什么品牌|创始人|老板是|哪里人|哪儿人|哪国人|产地|原产|"
        r"哪里|哪儿|什么地方|什么动物|哪种|哪一年|哪年|多大|多高|多长|多重|什么品种|是什么|几米|尺寸|身高",
        raw,
    ):
        return None
    if re.search(r"化学式|等于几|等于多少|天气|怎么做|如何煮|推荐", raw):
        return None
    known = {name for name in (known_names or []) if name and len(name) >= 2}
    known.update(_CAPITALS)
    known.update(_CHECKED_SIDES)
    names = [
        token for token in re.findall(r"[\u4e00-\u9fff]{2,8}", raw)
        if token not in _STOP and token not in known and not any(token in country or country in token for country in _CAPITALS)
    ]
    if names:
        return "我不知道。"
    return None

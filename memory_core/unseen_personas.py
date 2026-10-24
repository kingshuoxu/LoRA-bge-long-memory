"""用固定种子生成验收人设。

句式是通用的主谓结构，名字从音节里拼，不取调参集、已有验收集，
也不取用户报告里那四个人。问题换一种说法，不把原句再问一遍。
"""
from __future__ import annotations

import random

SEED = 20261025

_BLOCK = {
    "周晚宁", "陈拾光", "许知夏", "江澄月", "苏小北",
    "林晚舟", "顾清和", "沈星河", "顾云栖",
    "柏若岚", "星禾科技", "星禾",
    "沈若衡", "澜汐生物", "澜汐",
    "岑衡川", "云篆智造", "云篆", "裴临川",
    "Maren Holst", "Cobalt Reef Instruments", "Sigrid Vale",
    "Lysandra Keene", "Meridian Moss Analytics",
}


def _zh_name(rng: random.Random, syllables: list[str], size: int) -> str:
    for _ in range(40):
        name = "".join(rng.choice(syllables) for _ in range(size))
        if name not in _BLOCK and len(set(name)) == size:
            return name
    raise RuntimeError("没有拼出可用的名字")


def _en_name(rng: random.Random, first: list[str], last: list[str]) -> str:
    for _ in range(40):
        name = f"{rng.choice(first)} {rng.choice(last)}"
        if name not in _BLOCK:
            return name
    raise RuntimeError("没有拼出可用的英文名")


def build(seed: int = SEED) -> dict:
    rng = random.Random(seed)
    person = _zh_name(rng, ["清", "禾", "澜", "昭", "屿", "澄", "遥", "晏", "澈", "予", "闻", "栖"], 3)
    org = _zh_name(rng, ["霁", "川", "衡", "石", "岭", "浦", "杉", "泽"], 2) + "工坊"
    swapped = person[:-1] + ("秋" if not person.endswith("秋") else "冬")
    org_sub = org[:-1] + ("社" if not org.endswith("社") else "会")
    city = rng.choice(["临江市", "听潮市", "望野市"])
    town = rng.choice(["青柘镇", "白苇镇", "松浦镇"])
    job = rng.choice(["漆器师", "笺纸师", "织造师"])
    flower = rng.choice(["木香花", "紫藤花", "玉簪花"])
    pet = rng.choice(["阿栗", "小山", "豆青"])
    dog = rng.choice(["炭丸", "雪团", "椒盐"])
    founder = rng.choice(["宋清和", "叶晚照", "罗知微", "韩予安"])
    year = rng.choice(["2004", "2008", "2016"])
    hq = rng.choice(["嘉兴", "绍兴", "湖州"])
    product = rng.choice(["手动磨豆机", "陶瓷滤杯", "亚麻笔记本"])
    staff = rng.choice(["四十二人", "六十人", "八十五人"])
    cat = rng.choice(["年糕", "乌梅", "芝麻"])

    en_person = _en_name(rng, ["Liora", "Edith", "Soren", "Willa"], ["Peck", "Adler", "Voss", "Keene"])
    en_org = rng.choice([
        name for name in ("Northglass Works", "Hollowreed Studio", "Paperlantern Lab")
        if name not in _BLOCK
    ])
    en_city = rng.choice(["Ashmere", "Brindle", "Cairnholt"])
    en_town = rng.choice(["Port Sable", "Redwick", "Elmharbor"])
    en_job = rng.choice(["printmaker", "cartographer", "glassblower"])
    en_instrument = rng.choice(["viola", "clarinet", "mandolin"])
    en_pet = rng.choice(["Cinder", "Pebble", "Nutmeg"])
    en_color = rng.choice(["amber", "indigo", "copper"])
    en_founder = _en_name(rng, ["Ida", "Jules", "Noor"], ["Ferris", "Okada", "Beltran"])
    en_year = rng.choice(["1994", "2001", "2007"])
    en_base = rng.choice(["Halver", "Marrowgate", "Siltford"])
    en_product = rng.choice(["linen notebook", "ceramic filter", "hand mill"])
    en_cat = rng.choice(["Biscuit", "Miso", "Tinder"])
    en_staff = rng.choice(["36", "58", "74"])
    car_color = rng.choice(["珍珠白", "墨黑", "藏青"])

    zh_person_sentences = [
        f"{person}的猫叫{pet}。",
        f"{person}住在{city}。",
        f"{person}的职业是{job}。",
        f"{person}最喜欢的花是{flower}。",
        f"{person}的家乡是{town}。",
        f"{person}养了一只狗，名字叫{dog}。",
        f"{person}的汽车是{car_color}。",
    ]
    zh_org_sentences = [
        f"{org}成立于{year}年。",
        f"{org}的总部在{hq}。",
        f"{org}的创始人是{founder}。",
        f"{org}的主打产品是{product}。",
        f"{org}养了一只猫，名字叫{cat}。",
        f"{org}的员工人数是{staff}。",
    ]
    en_person_sentences = [
        f"{en_person}'s parrot is named {en_pet}.",
        f"{en_person} lives in {en_city}.",
        f"{en_person} works as a {en_job}.",
        f"{en_person} plays the {en_instrument}.",
        f"{en_person}'s hometown is {en_town}.",
        f"{en_person}'s car is {en_color}.",
    ]
    possessive = "'" if en_org.endswith(("s", "S")) else "'s"
    en_org_text = (
        f"{en_org} was founded in {en_year}. It is based in {en_base}. "
        f"Its founder is {en_founder}. {en_org}{possessive} flagship product is {en_product}. "
        f"{en_org} has an office cat named {en_cat}. It has {en_staff} employees."
    )
    return {
        "seed": seed,
        "zh": [
            {"title": person, "sentences": zh_person_sentences, "facts": [
                (pet, "name"), (city, "residence"), (job, "occupation"),
                (flower, "like"), (town, "origin"), (dog, "name"), (car_color, "color"),
            ]},
            {"title": org, "sentences": zh_org_sentences, "facts": [
                (year, "founding"), (hq, "headquarters"), (founder, "founder"),
                (product, "product"), (cat, "name"), (staff, "headcount"),
            ]},
        ],
        "en": [
            {"title": en_person, "sentences": en_person_sentences, "facts": [
                (en_pet, "name"), (en_city, "residence"), (en_job, "occupation"),
                (en_instrument, "instrument"), (en_town, "origin"), (en_color, "color"),
            ]},
            {"title": en_org, "sentences": [en_org_text], "facts": [
                (en_year, "founding"), (en_base, "headquarters"), (en_founder, "founder"),
                (en_product, "product"), (en_cat, "name"), (en_staff, "headcount"),
            ]},
        ],
        "zh_recall": [
            (f"{person}现居哪座城市？", city),
            (f"{person}是做什么工作的？", job),
            (f"{person}靠什么手艺谋生？", job),
            (f"{person}老家是哪里？", town),
            (f"{person}是在哪里长大的？", town),
            (f"{person}家的猫咪叫什么", pet),
            (f"{person}养的狗叫什么名字？", dog),
            (f"{person}的汽车是什么颜色？", car_color),
            (f"{person}开的车是什么颜色？", car_color),
            (f"{org}是哪一年创立的？", year),
            (f"{org}什么时候成立的？", year),
            (f"{org}总部设在哪个城市？", hq),
            (f"{org}是谁创办的？", founder),
            (f"{org}养的猫叫什么？", cat),
            (f"{org}主打什么产品？", product),
            (f"{org}有多少员工？", staff),
            (f"{org}成立于哪一年？", year),
            (f"{person}偏爱哪种花？", flower),
            (f"{person}的车啥颜色？", car_color),
            (f"{org}主要卖什么产品？", product),
        ],
        "zh_open": [
            (f"介绍一下{person}", pet),
            (f"告诉我{org}相关信息", product),
            (f"overview of {person}", pet),
            (f"everything about {org}", product),
        ],
        "zh_near": [
            (f"{person}兰的猫叫什么？", pet),
            (f"{person[:-1]}的家乡是哪里？", town),
            (f"{swapped}住在哪里？", city),
            (f"{org}公司 Inc 的创始人是谁？", founder),
            (f"{org}集团的总部在哪里？", hq),
            (f"{org_sub}成立于哪一年？", year),
            (f"overview of {person[:-1]}", pet),
            (f"everything about {org_sub}", product),
        ],
        "zh_yes": [
            (f"{person}住在{city}吗？", True, city),
            (f"{person}是医生吗？", False, job),
            (f"{org}的创始人是马云吗？", False, founder),
            (f"{org}是{year}年成立的吗？", True, year),
        ],
        "zh_abstain": [
            f"{person}的猫几岁了？",
            f"{person}最讨厌的花是什么？",
            f"{person}多高？",
            f"{person}的生日是什么时候？",
            f"{person}会弹古筝吗？",
            f"{person}毕业于哪所大学？",
            f"{org}的股票代码是多少？",
        ],
        "en_recall": [
            (f"Where does {en_person} reside?", en_city),
            (f"Which town is {en_person} living in?", en_city),
            (f"What does {en_person} do for a living?", en_job),
            (f"What is {en_person}'s profession?", en_job),
            (f"Where is {en_person} originally from?", en_town),
            (f"Where did {en_person} grow up?", en_town),
            (f"Which musical instrument does {en_person} play?", en_instrument),
            (f"When was {en_org} established?", en_year),
            (f"What year did {en_org} start?", en_year),
            (f"Where is {en_org} based?", en_base),
            (f"Who is the founder of {en_org}?", en_founder),
            (f"What is {en_org}'s main product?", en_product),
            (f"What is {en_org}{possessive} flagship product?", en_product),
            (f"What is the office cat at {en_org} called?", en_cat),
            (f"How many employees does {en_org} have?", en_staff),
        ],
        "en_yes": [
            (f"Does {en_person} live in {en_city}?", True, en_city),
            (f"Was {en_org} founded in 1901?", False, en_year),
            (f"Is {en_org} based in Paris?", False, en_base),
            (f"Is the {en_org} office cat named {en_cat}?", True, en_cat),
            (f"Is {en_person} a {en_job}?", True, en_job),
            (f"Is {en_person} a surgeon?", False, en_job),
            (f"Did {en_founder} found {en_org}?", True, en_founder),
            (f"Did Ada Lovelace found {en_org}?", False, en_founder),
        ],
        "en_open": [
            (f"Give me an overview of {en_org}", en_product),
            (f"Tell me everything about {en_person}", en_city),
        ],
        "en_near": [
            (f"Who founded {en_org} Inc?", en_founder),
        ],
        "en_abstain": [
            f"How old is {en_person}'s parrot?",
            f"What is {en_person}'s email address?",
            f"What breed is {en_org}'s cat?",
            f"In what year did {en_org} go public?",
        ],
        "general": [
            "水的化学式是什么？",
            "法国的首都是哪里？",
            "What is machine learning?",
            "How do I make cold brew coffee?",
            "1加1等于几？",
        ],
        "statements": [
            "我的猫猫叫咪咪",
            "My favorite color is blue.",
        ],
    }

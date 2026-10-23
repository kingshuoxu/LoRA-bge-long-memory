"""未见过的人物套件：调阈值只用 TUNE，报告和 CI 看 HELD。

每个人约 8 条事实，每条至少 3 个改写，外加是非、否定、没写过和串属性的问题。
改写故意不重复 structural_questions 里的原词问法，避免自己跟自己比。
"""
from __future__ import annotations

from memory_core.extract import pattern_extract
from memory_core.fact_span import build_fact_bank
from memory_core.paraphrase import adjudicate, polar_question, polar_reply_from_fact, structural_questions
from memory_core.prompts import has_cjk


def _zh(name: str, facts: list[dict]) -> dict:
    return {"id": name, "lang": "zh", "name": name, "facts": facts}


def _en(name: str, facts: list[dict]) -> dict:
    return {"id": name, "lang": "en", "name": name, "facts": facts}


def _color(name: str, obj: str, value: str, paraphrases: list[str]) -> dict:
    return {
        "statement": f"{name}的{obj}是{value}",
        "value": value,
        "paraphrases": paraphrases,
        "yes": f"{name}的{obj}是不是{value}",
        "no": f"{name}的{obj}是不是藏青色的吗" if "色" in value else f"{name}的{obj}是不是别的吗",
    }


# 调参分片。阈值和属性规则只看这里，不看 HELD。
TUNE = [
    _zh("周晚宁", [
        {"statement": "周晚宁的自行车是墨绿色的", "value": "墨绿色的", "paraphrases": [
            "周晚宁那辆自行车是啥颜色？", "周晚宁的自行车涂的什么色？", "周晚宁自行车的颜色是？",
        ]},
        {"statement": "周晚宁的狗叫年糕", "value": "年糕", "paraphrases": [
            "周晚宁家的狗叫啥？", "周晚宁养的那只狗怎么称呼？", "周晚宁的狗有什么名字？",
        ]},
        {"statement": "周晚宁住在桐溪镇", "value": "桐溪镇", "paraphrases": [
            "周晚宁家住在哪？", "周晚宁住在什么地方？", "周晚宁的家在哪个地方？",
        ]},
        {"statement": "周晚宁的乐器是琵琶", "value": "琵琶", "paraphrases": [
            "周晚宁会什么乐器？", "周晚宁弹的是什么乐器？", "周晚宁的乐器是哪一种？",
        ]},
        {"statement": "周晚宁最喜欢的茶是白毫银针", "value": "白毫银针", "paraphrases": [
            "周晚宁爱喝什么茶？", "周晚宁常喝的茶是什么？", "周晚宁喜欢哪种茶？",
        ]},
        {"statement": "周晚宁的汽车是藏青色的", "value": "藏青色的", "paraphrases": [
            "周晚宁的汽车是啥颜色？", "周晚宁那辆汽车涂的什么色？", "周晚宁汽车的颜色是？",
        ]},
        {"statement": "周晚宁的手表品牌是精工", "value": "精工", "paraphrases": [
            "周晚宁的手表是什么牌子？", "周晚宁戴的手表什么品牌？", "周晚宁手表的牌子是？",
        ]},
        {"statement": "周晚宁的早餐是葱油饼", "value": "葱油饼", "paraphrases": [
            "周晚宁早上吃什么？", "周晚宁的早饭是什么？", "周晚宁早餐一般吃啥？",
        ]},
    ]),
    _zh("陈拾光", [
        {"statement": "陈拾光的自行车是鹅黄色的", "value": "鹅黄色的", "paraphrases": [
            "陈拾光那辆自行车是啥颜色？", "陈拾光的自行车涂的什么色？", "陈拾光自行车的颜色是？",
        ]},
        {"statement": "陈拾光的猫叫糯米", "value": "糯米", "paraphrases": [
            "陈拾光家的猫叫啥？", "陈拾光养的那只猫怎么称呼？", "陈拾光的猫有什么名字？",
        ]},
        {"statement": "陈拾光住在澄江县", "value": "澄江县", "paraphrases": [
            "陈拾光家住在哪？", "陈拾光住在什么地方？", "陈拾光的家在哪个地方？",
        ]},
        {"statement": "陈拾光的乐器是二胡", "value": "二胡", "paraphrases": [
            "陈拾光会什么乐器？", "陈拾光拉的是什么乐器？", "陈拾光的乐器是哪一种？",
        ]},
        {"statement": "陈拾光最喜欢的茶是铁观音", "value": "铁观音", "paraphrases": [
            "陈拾光爱喝什么茶？", "陈拾光常喝的茶是什么？", "陈拾光喜欢哪种茶？",
        ]},
        {"statement": "陈拾光的汽车是银灰色的", "value": "银灰色的", "paraphrases": [
            "陈拾光的汽车是啥颜色？", "陈拾光那辆汽车涂的什么色？", "陈拾光汽车的颜色是？",
        ]},
        {"statement": "陈拾光的钢笔品牌是百乐", "value": "百乐", "paraphrases": [
            "陈拾光的钢笔是什么牌子？", "陈拾光用的钢笔什么品牌？", "陈拾光钢笔的牌子是？",
        ]},
        {"statement": "陈拾光的早餐是小米粥", "value": "小米粥", "paraphrases": [
            "陈拾光早上吃什么？", "陈拾光的早饭是什么？", "陈拾光早餐一般吃啥？",
        ]},
    ]),
    _zh("许知夏", [
        {"statement": "许知夏的自行车是天蓝色的", "value": "天蓝色的", "paraphrases": [
            "许知夏那辆自行车是啥颜色？", "许知夏的自行车涂的什么色？", "许知夏自行车的颜色是？",
        ]},
        {"statement": "许知夏的狗叫布丁", "value": "布丁", "paraphrases": [
            "许知夏家的狗叫啥？", "许知夏养的那只狗怎么称呼？", "许知夏的狗有什么名字？",
        ]},
        {"statement": "许知夏住在石梁乡", "value": "石梁乡", "paraphrases": [
            "许知夏家住在哪？", "许知夏住在什么地方？", "许知夏的家在哪个地方？",
        ]},
        {"statement": "许知夏的乐器是古筝", "value": "古筝", "paraphrases": [
            "许知夏会什么乐器？", "许知夏弹的是什么乐器？", "许知夏的乐器是哪一种？",
        ]},
        {"statement": "许知夏最喜欢的茶是龙井", "value": "龙井", "paraphrases": [
            "许知夏爱喝什么茶？", "许知夏常喝的茶是什么？", "许知夏喜欢哪种茶？",
        ]},
        {"statement": "许知夏的汽车是墨黑色的", "value": "墨黑色的", "paraphrases": [
            "许知夏的汽车是啥颜色？", "许知夏那辆汽车涂的什么色？", "许知夏汽车的颜色是？",
        ]},
        {"statement": "许知夏的耳机品牌是索尼", "value": "索尼", "paraphrases": [
            "许知夏的耳机是什么牌子？", "许知夏用的耳机什么品牌？", "许知夏耳机的牌子是？",
        ]},
        {"statement": "许知夏的早餐是豆浆", "value": "豆浆", "paraphrases": [
            "许知夏早上吃什么？", "许知夏的早饭是什么？", "许知夏早餐一般吃啥？",
        ]},
    ]),
    _zh("江澄月", [
        {"statement": "江澄月的自行车是橘红色的", "value": "橘红色的", "paraphrases": [
            "江澄月那辆自行车是啥颜色？", "江澄月的自行车涂的什么色？", "江澄月自行车的颜色是？",
        ]},
        {"statement": "江澄月的猫叫汤圆", "value": "汤圆", "paraphrases": [
            "江澄月家的猫叫啥？", "江澄月养的那只猫怎么称呼？", "江澄月的猫有什么名字？",
        ]},
        {"statement": "江澄月住在南浦镇", "value": "南浦镇", "paraphrases": [
            "江澄月家住在哪？", "江澄月住在什么地方？", "江澄月的家在哪个地方？",
        ]},
        {"statement": "江澄月的乐器是长笛", "value": "长笛", "paraphrases": [
            "江澄月会什么乐器？", "江澄月吹的是什么乐器？", "江澄月的乐器是哪一种？",
        ]},
        {"statement": "江澄月最喜欢的茶是普洱", "value": "普洱", "paraphrases": [
            "江澄月爱喝什么茶？", "江澄月常喝的茶是什么？", "江澄月喜欢哪种茶？",
        ]},
        {"statement": "江澄月的汽车是米白色的", "value": "米白色的", "paraphrases": [
            "江澄月的汽车是啥颜色？", "江澄月那辆汽车涂的什么色？", "江澄月汽车的颜色是？",
        ]},
        {"statement": "江澄月的相机品牌是富士", "value": "富士", "paraphrases": [
            "江澄月的相机是什么牌子？", "江澄月用的相机什么品牌？", "江澄月相机的牌子是？",
        ]},
        {"statement": "江澄月的早餐是馄饨", "value": "馄饨", "paraphrases": [
            "江澄月早上吃什么？", "江澄月的早饭是什么？", "江澄月早餐一般吃啥？",
        ]},
    ]),
    _zh("苏小北", [
        {"statement": "苏小北的自行车是湖蓝色的", "value": "湖蓝色的", "paraphrases": [
            "苏小北那辆自行车是啥颜色？", "苏小北的自行车涂的什么色？", "苏小北自行车的颜色是？",
        ]},
        {"statement": "苏小北的狗叫麻薯", "value": "麻薯", "paraphrases": [
            "苏小北家的狗叫啥？", "苏小北养的那只狗怎么称呼？", "苏小北的狗有什么名字？",
        ]},
        {"statement": "苏小北住在枫林镇", "value": "枫林镇", "paraphrases": [
            "苏小北家住在哪？", "苏小北住在什么地方？", "苏小北的家在哪个地方？",
        ]},
        {"statement": "苏小北的乐器是小提琴", "value": "小提琴", "paraphrases": [
            "苏小北会什么乐器？", "苏小北拉的是什么乐器？", "苏小北的乐器是哪一种？",
        ]},
        {"statement": "苏小北最喜欢的茶是茉莉花茶", "value": "茉莉花茶", "paraphrases": [
            "苏小北爱喝什么茶？", "苏小北常喝的茶是什么？", "苏小北喜欢哪种茶？",
        ]},
        {"statement": "苏小北的汽车是深绿色的", "value": "深绿色的", "paraphrases": [
            "苏小北的汽车是啥颜色？", "苏小北那辆汽车涂的什么色？", "苏小北汽车的颜色是？",
        ]},
        {"statement": "苏小北的包品牌是无印良品", "value": "无印良品", "paraphrases": [
            "苏小北的包是什么牌子？", "苏小北背的包什么品牌？", "苏小北包的牌子是？",
        ]},
        {"statement": "苏小北的早餐是油条", "value": "油条", "paraphrases": [
            "苏小北早上吃什么？", "苏小北的早饭是什么？", "苏小北早餐一般吃啥？",
        ]},
    ]),
    _en("Helen Cho", [
        {"statement": "Helen Cho's bicycle is teal", "value": "teal", "paraphrases": [
            "What colour is Helen Cho's bicycle?", "Helen Cho's bicycle is which colour?", "Which colour is Helen Cho's bicycle?",
        ]},
        {"statement": "Helen Cho's dog is named Miso", "value": "Miso", "paraphrases": [
            "What is the name of the dog Helen Cho keeps?", "Helen Cho's dog is called what?", "Who is Helen Cho's dog?",
        ]},
        {"statement": "Helen Cho lives in Redcliff", "value": "Redcliff", "paraphrases": [
            "Where does Helen Cho live?", "Where is Helen Cho's home?", "What is Helen Cho's address?",
        ]},
        {"statement": "Helen Cho's instrument is the violin", "value": "violin", "paraphrases": [
            "What instrument does Helen Cho play?", "Helen Cho plays which instrument?", "What is Helen Cho's instrument?",
        ]},
        {"statement": "Helen Cho's favorite tea is sencha", "value": "sencha", "paraphrases": [
            "What tea does Helen Cho like?", "Which tea is Helen Cho's favorite?", "What is Helen Cho's favorite tea?",
        ]},
        {"statement": "Helen Cho's car is silver", "value": "silver", "paraphrases": [
            "What colour is Helen Cho's car?", "Helen Cho's car is what colour?", "Which colour is Helen Cho's car?",
        ]},
        {"statement": "Helen Cho's watch brand is Casio", "value": "Casio", "paraphrases": [
            "What brand is Helen Cho's watch?", "Helen Cho's watch is which brand?", "What is the brand of Helen Cho's watch?",
        ]},
        {"statement": "Helen Cho's breakfast is congee", "value": "congee", "paraphrases": [
            "What does Helen Cho eat for breakfast?", "Helen Cho's breakfast is what?", "What is Helen Cho's breakfast?",
        ]},
    ]),
    _en("Owen Blake", [
        {"statement": "Owen Blake's bicycle is maroon", "value": "maroon", "paraphrases": [
            "What colour is Owen Blake's bicycle?", "Owen Blake's bicycle is which colour?", "Which colour is Owen Blake's bicycle?",
        ]},
        {"statement": "Owen Blake's cat is named Noodle", "value": "Noodle", "paraphrases": [
            "What is the name of the cat Owen Blake keeps?", "Owen Blake's cat is called what?", "Who is Owen Blake's cat?",
        ]},
        {"statement": "Owen Blake lives in Harrowgate", "value": "Harrowgate", "paraphrases": [
            "Where does Owen Blake live?", "Where is Owen Blake's home?", "What is Owen Blake's address?",
        ]},
        {"statement": "Owen Blake's instrument is the cello", "value": "cello", "paraphrases": [
            "What instrument does Owen Blake play?", "Owen Blake plays which instrument?", "What is Owen Blake's instrument?",
        ]},
        {"statement": "Owen Blake's favorite tea is assam", "value": "assam", "paraphrases": [
            "What tea does Owen Blake like?", "Which tea is Owen Blake's favorite?", "What is Owen Blake's favorite tea?",
        ]},
        {"statement": "Owen Blake's car is green", "value": "green", "paraphrases": [
            "What colour is Owen Blake's car?", "Owen Blake's car is what colour?", "Which colour is Owen Blake's car?",
        ]},
        {"statement": "Owen Blake's pen brand is Lamy", "value": "Lamy", "paraphrases": [
            "What brand is Owen Blake's pen?", "Owen Blake's pen is which brand?", "What is the brand of Owen Blake's pen?",
        ]},
        {"statement": "Owen Blake's breakfast is oats", "value": "oats", "paraphrases": [
            "What does Owen Blake eat for breakfast?", "Owen Blake's breakfast is what?", "What is Owen Blake's breakfast?",
        ]},
    ]),
    _en("Priya Nair", [
        {"statement": "Priya Nair's bicycle is ivory", "value": "ivory", "paraphrases": [
            "What colour is Priya Nair's bicycle?", "Priya Nair's bicycle is which colour?", "Which colour is Priya Nair's bicycle?",
        ]},
        {"statement": "Priya Nair's dog is named Pepper", "value": "Pepper", "paraphrases": [
            "What is the name of the dog Priya Nair keeps?", "Priya Nair's dog is called what?", "Who is Priya Nair's dog?",
        ]},
        {"statement": "Priya Nair lives in Westford", "value": "Westford", "paraphrases": [
            "Where does Priya Nair live?", "Where is Priya Nair's home?", "What is Priya Nair's address?",
        ]},
        {"statement": "Priya Nair's instrument is the flute", "value": "flute", "paraphrases": [
            "What instrument does Priya Nair play?", "Priya Nair plays which instrument?", "What is Priya Nair's instrument?",
        ]},
        {"statement": "Priya Nair's favorite tea is darjeeling", "value": "darjeeling", "paraphrases": [
            "What tea does Priya Nair like?", "Which tea is Priya Nair's favorite?", "What is Priya Nair's favorite tea?",
        ]},
        {"statement": "Priya Nair's car is black", "value": "black", "paraphrases": [
            "What colour is Priya Nair's car?", "Priya Nair's car is what colour?", "Which colour is Priya Nair's car?",
        ]},
        {"statement": "Priya Nair's camera brand is Nikon", "value": "Nikon", "paraphrases": [
            "What brand is Priya Nair's camera?", "Priya Nair's camera is which brand?", "What is the brand of Priya Nair's camera?",
        ]},
        {"statement": "Priya Nair's breakfast is idli", "value": "idli", "paraphrases": [
            "What does Priya Nair eat for breakfast?", "Priya Nair's breakfast is what?", "What is Priya Nair's breakfast?",
        ]},
    ]),
    _en("Jonah Ellis", [
        {"statement": "Jonah Ellis's bicycle is navy", "value": "navy", "paraphrases": [
            "What colour is Jonah Ellis's bicycle?", "Jonah Ellis's bicycle is which colour?", "Which colour is Jonah Ellis's bicycle?",
        ]},
        {"statement": "Jonah Ellis's dog is named Biscuit", "value": "Biscuit", "paraphrases": [
            "What is the name of the dog Jonah Ellis keeps?", "Jonah Ellis's dog is called what?", "Who is Jonah Ellis's dog?",
        ]},
        {"statement": "Jonah Ellis lives in Millhaven", "value": "Millhaven", "paraphrases": [
            "Where does Jonah Ellis live?", "Where is Jonah Ellis's home?", "What is Jonah Ellis's address?",
        ]},
        {"statement": "Jonah Ellis's instrument is the trumpet", "value": "trumpet", "paraphrases": [
            "What instrument does Jonah Ellis play?", "Jonah Ellis plays which instrument?", "What is Jonah Ellis's instrument?",
        ]},
        {"statement": "Jonah Ellis's favorite tea is oolong", "value": "oolong", "paraphrases": [
            "What tea does Jonah Ellis like?", "Which tea is Jonah Ellis's favorite?", "What is Jonah Ellis's favorite tea?",
        ]},
        {"statement": "Jonah Ellis's car is white", "value": "white", "paraphrases": [
            "What colour is Jonah Ellis's car?", "Jonah Ellis's car is what colour?", "Which colour is Jonah Ellis's car?",
        ]},
        {"statement": "Jonah Ellis's bag brand is Fjallraven", "value": "Fjallraven", "paraphrases": [
            "What brand is Jonah Ellis's bag?", "Jonah Ellis's bag is which brand?", "What is the brand of Jonah Ellis's bag?",
        ]},
        {"statement": "Jonah Ellis's breakfast is toast", "value": "toast", "paraphrases": [
            "What does Jonah Ellis eat for breakfast?", "Jonah Ellis's breakfast is what?", "What is Jonah Ellis's breakfast?",
        ]},
    ]),
    _en("Rosa Bennett", [
        {"statement": "Rosa Bennett's bicycle is coral", "value": "coral", "paraphrases": [
            "What colour is Rosa Bennett's bicycle?", "Rosa Bennett's bicycle is which colour?", "Which colour is Rosa Bennett's bicycle?",
        ]},
        {"statement": "Rosa Bennett's cat is named Pebble", "value": "Pebble", "paraphrases": [
            "What is the name of the cat Rosa Bennett keeps?", "Rosa Bennett's cat is called what?", "Who is Rosa Bennett's cat?",
        ]},
        {"statement": "Rosa Bennett lives in Ashbourne", "value": "Ashbourne", "paraphrases": [
            "Where does Rosa Bennett live?", "Where is Rosa Bennett's home?", "What is Rosa Bennett's address?",
        ]},
        {"statement": "Rosa Bennett's instrument is the harp", "value": "harp", "paraphrases": [
            "What instrument does Rosa Bennett play?", "Rosa Bennett plays which instrument?", "What is Rosa Bennett's instrument?",
        ]},
        {"statement": "Rosa Bennett's favorite tea is matcha", "value": "matcha", "paraphrases": [
            "What tea does Rosa Bennett like?", "Which tea is Rosa Bennett's favorite?", "What is Rosa Bennett's favorite tea?",
        ]},
        {"statement": "Rosa Bennett's car is red", "value": "red", "paraphrases": [
            "What colour is Rosa Bennett's car?", "Rosa Bennett's car is what colour?", "Which colour is Rosa Bennett's car?",
        ]},
        {"statement": "Rosa Bennett's headphone brand is Sony", "value": "Sony", "paraphrases": [
            "What brand is Rosa Bennett's headphone?", "Rosa Bennett's headphone is which brand?", "What is the brand of Rosa Bennett's headphone?",
        ]},
        {"statement": "Rosa Bennett's breakfast is yogurt", "value": "yogurt", "paraphrases": [
            "What does Rosa Bennett eat for breakfast?", "Rosa Bennett's breakfast is what?", "What is Rosa Bennett's breakfast?",
        ]},
    ]),
]


# 报告用。林晚舟 / Marcus Whitfield 是独立复核用过的人，不参与调参。
HELD = [
    _zh("林晚舟", [
        {"statement": "林晚舟的自行车是朱红色的", "value": "朱红色的", "paraphrases": [
            "林晚舟那辆自行车是啥颜色？", "林晚舟的自行车涂的什么色？", "林晚舟自行车的颜色是？",
        ]},
        {"statement": "林晚舟的狗叫豆包", "value": "豆包", "paraphrases": [
            "林晚舟家的狗叫啥？", "林晚舟养的那只狗怎么称呼？", "林晚舟的狗有什么名字？",
        ]},
        {"statement": "林晚舟住在临安", "value": "临安", "paraphrases": [
            "林晚舟家住在哪？", "林晚舟住在什么地方？", "林晚舟的家在哪个地方？",
        ]},
        {"statement": "林晚舟的乐器是笛子", "value": "笛子", "paraphrases": [
            "林晚舟会什么乐器？", "林晚舟吹的是什么乐器？", "林晚舟的乐器是哪一种？",
        ]},
        {"statement": "林晚舟最喜欢的茶是桂花乌龙", "value": "桂花乌龙", "paraphrases": [
            "林晚舟爱喝什么茶？", "林晚舟常喝的茶是什么？", "林晚舟喜欢哪种茶？",
        ]},
        {"statement": "林晚舟的汽车是藏青色的", "value": "藏青色的", "paraphrases": [
            "林晚舟的汽车是啥颜色？", "林晚舟那辆汽车涂的什么色？", "林晚舟汽车的颜色是？",
        ]},
        {"statement": "林晚舟的手表品牌是精工", "value": "精工", "paraphrases": [
            "林晚舟的手表是什么牌子？", "林晚舟戴的手表什么品牌？", "林晚舟手表的牌子是？",
        ]},
        {"statement": "林晚舟的早餐是葱油饼", "value": "葱油饼", "paraphrases": [
            "林晚舟早上吃什么？", "林晚舟的早饭是什么？", "林晚舟早餐一般吃啥？",
        ]},
    ]),
    _zh("顾清和", [
        {"statement": "顾清和的自行车是姜黄色的", "value": "姜黄色的", "paraphrases": [
            "顾清和那辆自行车是啥颜色？", "顾清和的自行车涂的什么色？", "顾清和自行车的颜色是？",
        ]},
        {"statement": "顾清和的狗叫核桃", "value": "核桃", "paraphrases": [
            "顾清和家的狗叫啥？", "顾清和养的那只狗怎么称呼？", "顾清和的狗有什么名字？",
        ]},
        {"statement": "顾清和住在青田", "value": "青田", "paraphrases": [
            "顾清和家住在哪？", "顾清和住在什么地方？", "顾清和的家在哪个地方？",
        ]},
        {"statement": "顾清和的乐器是阮", "value": "阮", "paraphrases": [
            "顾清和会什么乐器？", "顾清和弹的是什么乐器？", "顾清和的乐器是哪一种？",
        ]},
        {"statement": "顾清和最喜欢的茶是白茶", "value": "白茶", "paraphrases": [
            "顾清和爱喝什么茶？", "顾清和常喝的茶是什么？", "顾清和喜欢哪种茶？",
        ]},
        {"statement": "顾清和的汽车是海蓝色的", "value": "海蓝色的", "paraphrases": [
            "顾清和的汽车是啥颜色？", "顾清和那辆汽车涂的什么色？", "顾清和汽车的颜色是？",
        ]},
        {"statement": "顾清和的杯子品牌是象印", "value": "象印", "paraphrases": [
            "顾清和的杯子是什么牌子？", "顾清和用的杯子什么品牌？", "顾清和杯子的牌子是？",
        ]},
        {"statement": "顾清和的早餐是包子", "value": "包子", "paraphrases": [
            "顾清和早上吃什么？", "顾清和的早饭是什么？", "顾清和早餐一般吃啥？",
        ]},
    ]),
    _en("Marcus Whitfield", [
        {"statement": "Marcus Whitfield's bicycle is vermilion", "value": "vermilion", "paraphrases": [
            "What colour is Marcus Whitfield's bicycle?", "Marcus Whitfield's bicycle is which colour?", "Which colour is Marcus Whitfield's bicycle?",
        ]},
        {"statement": "Marcus Whitfield's dog is named Biscuit", "value": "Biscuit", "paraphrases": [
            "What is the name of the dog Marcus Whitfield keeps?", "Marcus Whitfield's dog is called what?", "Who is Marcus Whitfield's dog?",
        ]},
        {"statement": "Marcus Whitfield lives in Bristol", "value": "Bristol", "paraphrases": [
            "Where does Marcus Whitfield live?", "Where is Marcus Whitfield's home?", "What is Marcus Whitfield's address?",
        ]},
        {"statement": "Marcus Whitfield's instrument is the clarinet", "value": "clarinet", "paraphrases": [
            "What instrument does Marcus Whitfield play?", "Marcus Whitfield plays which instrument?", "What is Marcus Whitfield's instrument?",
        ]},
        {"statement": "Marcus Whitfield's favorite tea is jasmine", "value": "jasmine", "paraphrases": [
            "What tea does Marcus Whitfield like?", "Which tea is Marcus Whitfield's favorite?", "What is Marcus Whitfield's favorite tea?",
        ]},
        {"statement": "Marcus Whitfield's car is blue", "value": "blue", "paraphrases": [
            "What colour is Marcus Whitfield's car?", "Marcus Whitfield's car is what colour?", "Which colour is Marcus Whitfield's car?",
        ]},
        {"statement": "Marcus Whitfield's watch brand is Seiko", "value": "Seiko", "paraphrases": [
            "What brand is Marcus Whitfield's watch?", "Marcus Whitfield's watch is which brand?", "What is the brand of Marcus Whitfield's watch?",
        ]},
        {"statement": "Marcus Whitfield's breakfast is porridge", "value": "porridge", "paraphrases": [
            "What does Marcus Whitfield eat for breakfast?", "Marcus Whitfield's breakfast is what?", "What is Marcus Whitfield's breakfast?",
        ]},
    ]),
    _en("Nora Ellison", [
        {"statement": "Nora Ellison's bicycle is amber", "value": "amber", "paraphrases": [
            "What colour is Nora Ellison's bicycle?", "Nora Ellison's bicycle is which colour?", "Which colour is Nora Ellison's bicycle?",
        ]},
        {"statement": "Nora Ellison's dog is named Waffles", "value": "Waffles", "paraphrases": [
            "What is the name of the dog Nora Ellison keeps?", "Nora Ellison's dog is called what?", "Who is Nora Ellison's dog?",
        ]},
        {"statement": "Nora Ellison lives in Camden", "value": "Camden", "paraphrases": [
            "Where does Nora Ellison live?", "Where is Nora Ellison's home?", "What is Nora Ellison's address?",
        ]},
        {"statement": "Nora Ellison's instrument is the oboe", "value": "oboe", "paraphrases": [
            "What instrument does Nora Ellison play?", "Nora Ellison plays which instrument?", "What is Nora Ellison's instrument?",
        ]},
        {"statement": "Nora Ellison's favorite tea is keemun", "value": "keemun", "paraphrases": [
            "What tea does Nora Ellison like?", "Which tea is Nora Ellison's favorite?", "What is Nora Ellison's favorite tea?",
        ]},
        {"statement": "Nora Ellison's car is grey", "value": "grey", "paraphrases": [
            "What colour is Nora Ellison's car?", "Nora Ellison's car is what colour?", "Which colour is Nora Ellison's car?",
        ]},
        {"statement": "Nora Ellison's lamp brand is Ikea", "value": "Ikea", "paraphrases": [
            "What brand is Nora Ellison's lamp?", "Nora Ellison's lamp is which brand?", "What is the brand of Nora Ellison's lamp?",
        ]},
        {"statement": "Nora Ellison's breakfast is granola", "value": "granola", "paraphrases": [
            "What does Nora Ellison eat for breakfast?", "Nora Ellison's breakfast is what?", "What is Nora Ellison's breakfast?",
        ]},
    ]),
]


def _pet_word(persona: dict) -> str:
    for fact in persona["facts"]:
        statement = fact["statement"]
        if "的狗叫" in statement or "dog is named" in statement:
            return "狗" if has_cjk(statement) else "dog"
        if "的猫叫" in statement or "cat is named" in statement:
            return "猫" if has_cjk(statement) else "cat"
    return "狗" if persona["lang"] == "zh" else "dog"


def _pet_value(persona: dict) -> str:
    pet = _pet_word(persona)
    for fact in persona["facts"]:
        if pet == "狗" and "的狗叫" in fact["statement"]:
            return fact["value"]
        if pet == "猫" and "的猫叫" in fact["statement"]:
            return fact["value"]
        if pet == "dog" and "dog is named" in fact["statement"]:
            return fact["value"]
        if pet == "cat" and "cat is named" in fact["statement"]:
            return fact["value"]
    return ""


def extra_questions(persona: dict) -> dict[str, list]:
    """是非、否定、没写过、串到别的属性。这些不拿去调召回阈值的分子。"""
    name = persona["name"]
    pet = _pet_word(persona)
    pet_value = _pet_value(persona)
    home = next(fact["value"] for fact in persona["facts"] if "住在" in fact["statement"] or "lives in" in fact["statement"])
    if persona["lang"] == "zh":
        other = "猫" if pet == "狗" else "狗"
        yesno = [
            (f"{name}的{pet}是叫可乐吗？", "no", pet_value),
            (f"{name}的{pet}是叫{pet_value}吗？", "yes", pet_value),
            (f"{name}有没有养{pet}？", "have", pet_value),
            (f"{name}是不是住在上海？", "no", home),
            (f"{name}是不是住在{home}？", "yes", home),
            (f"{name}的{pet}不是叫可乐吧？", "no", pet_value),
        ]
        abstain = [
            f"{name}的{pet}是什么品种？",
            f"{name}的自行车贵不贵？",
            f"{name}的自行车是电动的吗？",
            f"{name}的{other}叫什么？",
            f"{name}的电话是多少？",
            f"{name}多大了？",
            f"{name}的老家在哪里？",
            f"{name}的妹妹叫什么？",
        ]
    else:
        other = "cat" if pet == "dog" else "dog"
        yesno = [
            (f"Is {name}'s {pet} named Rex?", "no", pet_value),
            (f"Is {name}'s {pet} called {pet_value}?", "yes", pet_value),
            (f"Does {name} have a {pet}?", "have", pet_value),
            (f"Does {name} live in Shanghai?", "no", home),
            (f"Does {name} live in {home}?", "yes", home),
            (f"Isn't {name}'s {pet} named Rex?", "no", pet_value),
        ]
        abstain = [
            f"What breed is {name}'s {pet}?",
            f"Is {name}'s bicycle expensive?",
            f"Is {name}'s bicycle electric?",
            f"What is {name}'s {other}'s name?",
            f"What is {name}'s phone number?",
            f"How old is {name}?",
            f"What is {name}'s sister's name?",
            f"What is {name}'s hometown?",
        ]
    return {"yesno": yesno, "abstain": abstain}


def correction_phrasings(name: str, old: str, new: str) -> list[str]:
    return [
        f"{name}'s dog is not {old}, it is {new}.",
        f"{name}'s dog isn't {old}. The dog is {new}.",
        f"The name of {name}'s dog is {new}, not {old}.",
        f"{name} has a dog named {new}, not {old}.",
        f"{new} is {name}'s dog, not {old}.",
    ]


CORRECTIONS = {
    "Marcus Whitfield": {"new": "Waffles", "lines": correction_phrasings("Marcus Whitfield", "Biscuit", "Waffles")},
    "Nora Ellison": {"new": "Marmalade", "lines": correction_phrasings("Nora Ellison", "Waffles", "Marmalade")},
}


def load_facts(persona: dict) -> list[dict]:
    from memory_core.paraphrase import filter_cross_fact

    found = []
    for spec in persona["facts"]:
        extracted = pattern_extract(spec["statement"])
        if not extracted:
            raise RuntimeError(f"{persona['id']} 抽不出：{spec['statement']}")
        fact = extracted[0]
        if spec["value"] not in fact["value"] and fact["value"] not in spec["value"]:
            raise RuntimeError(f"{persona['id']} 取值不对：{spec['statement']} -> {fact['value']}")
        fact["gate_questions"] = structural_questions(fact)
        found.append(fact)
    filter_cross_fact(found)
    return found


def _decide(question: str, bank, facts: list[dict]) -> dict:
    metas = [
        {
            "entity": fact.get("entity") or "",
            "attr": fact.get("attr") or "",
            "value": fact.get("value") or "",
            "question": fact.get("question") or "",
            "statement": fact.get("statement") or "",
        }
        for fact in facts
    ]
    info = bank.explain(question, metas=metas)
    if not info.get("matched"):
        alt = polar_question(question)
        if alt and alt != question:
            alt_info = bank.explain(alt, metas=metas)
            if alt_info.get("matched"):
                alt_info = dict(alt_info)
                alt_info["polar_of"] = question
                info = alt_info
    return adjudicate(question, info)


def _passed_fact(info: dict) -> dict | None:
    for fact in info.get("facts") or []:
        if fact.get("passed"):
            return fact
    return None


def score_persona(persona: dict) -> dict:
    facts = load_facts(persona)
    bank = build_fact_bank(facts)
    if bank is None:
        raise RuntimeError(f"{persona['id']} 没有事实银行")
    paraphrase_hits = 0
    paraphrase_total = 0
    wrong = []
    misses = []
    for spec in persona["facts"]:
        for question in spec["paraphrases"]:
            paraphrase_total += 1
            info = _decide(question, bank, facts)
            got = _passed_fact(info)
            if got and str(got.get("value") or "") == spec["value"]:
                paraphrase_hits += 1
            elif got:
                wrong.append((question, spec["value"], got.get("attr"), got.get("value"), info.get("best_question_sim")))
            else:
                best = next((item for item in info.get("facts") or [] if item.get("best")), {})
                misses.append((question, spec["value"], best.get("attr"), best.get("question_sim"), best.get("attr_sim")))
    extras = extra_questions(persona)
    yes_hits = 0
    yes_total = 0
    yes_misses = []
    for question, polarity, value in extras["yesno"]:
        yes_total += 1
        info = _decide(question, bank, facts)
        got = _passed_fact(info)
        reply = polar_reply_from_fact(question, got) if got else None
        ok_value = bool(got) and str(got.get("value") or "") == value
        if polarity == "yes":
            ok_word = bool(reply) and (reply.startswith("是") or reply.startswith("Yes"))
        elif polarity == "have":
            ok_word = bool(reply) and (reply.startswith("有") or reply.startswith("Yes"))
        else:
            ok_word = bool(reply) and (reply.startswith("不是") or reply.startswith("No"))
        if ok_value and ok_word and reply and value in reply:
            yes_hits += 1
        else:
            if got and str(got.get("value") or "") != value:
                wrong.append((question, value, got.get("attr"), got.get("value"), "yesno"))
            yes_misses.append((question, polarity, value, reply, None if not got else got.get("value")))
    abstain_hits = 0
    abstain_total = 0
    abstain_misses = []
    for question in extras["abstain"]:
        abstain_total += 1
        info = _decide(question, bank, facts)
        got = _passed_fact(info)
        if got is None:
            abstain_hits += 1
        else:
            wrong.append((question, None, got.get("attr"), got.get("value"), "abstain"))
            abstain_misses.append((question, got.get("attr"), got.get("value")))
    return {
        "id": persona["id"],
        "lang": persona["lang"],
        "paraphrase": (paraphrase_hits, paraphrase_total),
        "yesno": (yes_hits, yes_total),
        "abstain": (abstain_hits, abstain_total),
        "wrong": wrong,
        "misses": misses,
        "yes_misses": yes_misses,
        "abstain_misses": abstain_misses,
        "attrs": [(fact.get("attr"), fact.get("value")) for fact in facts],
    }


def _add(total: dict, row: dict) -> None:
    for key in ("paraphrase", "yesno", "abstain"):
        hits, count = row[key]
        total[key][0] += hits
        total[key][1] += count
    total["wrong"].extend((row["id"], item) for item in row["wrong"])
    total["rows"].append(row)


def score_split(personas: list[dict]) -> dict:
    total = {
        "paraphrase": [0, 0],
        "yesno": [0, 0],
        "abstain": [0, 0],
        "wrong": [],
        "rows": [],
        "by_lang": {},
    }
    for persona in personas:
        row = score_persona(persona)
        _add(total, row)
        bucket = total["by_lang"].setdefault(persona["lang"], {
            "paraphrase": [0, 0], "yesno": [0, 0], "abstain": [0, 0], "wrong": [], "rows": [],
        })
        _add(bucket, row)
    return total


def _fmt(pair: list[int] | tuple[int, int]) -> str:
    hits, count = pair
    if not count:
        return "0/0"
    return f"{hits}/{count} ({hits / count:.0%})"


def format_report(label: str, total: dict) -> str:
    lines = [
        f"{label} paraphrase {_fmt(total['paraphrase'])} yes/no {_fmt(total['yesno'])} "
        f"abstain {_fmt(total['abstain'])} wrong {len(total['wrong'])}"
    ]
    for lang, bucket in total["by_lang"].items():
        lines.append(
            f"  {lang} paraphrase {_fmt(bucket['paraphrase'])} yes/no {_fmt(bucket['yesno'])} "
            f"abstain {_fmt(bucket['abstain'])} wrong {len(bucket['wrong'])}"
        )
    return "\n".join(lines)


def assert_held_out(total: dict | None = None) -> dict:
    """CI 只卡没参与调参的人。不达标就让验收失败。"""
    total = total if total is not None else score_split(HELD)
    errors = []
    zh = total["by_lang"].get("zh") or {}
    en = total["by_lang"].get("en") or {}

    def rate(bucket: dict, key: str) -> float:
        hits, count = bucket.get(key) or (0, 0)
        return hits / count if count else 0.0

    if rate(zh, "paraphrase") < 0.90:
        errors.append(f"zh paraphrase { _fmt(zh.get('paraphrase', (0, 0))) }")
    if rate(en, "paraphrase") < 0.85:
        errors.append(f"en paraphrase { _fmt(en.get('paraphrase', (0, 0))) }")
    if rate(zh, "yesno") < 0.90 or rate(en, "yesno") < 0.90:
        errors.append(f"yes/no zh {_fmt(zh.get('yesno', (0, 0)))} en {_fmt(en.get('yesno', (0, 0)))}")
    if rate(zh, "abstain") < 0.95 or rate(en, "abstain") < 0.95:
        errors.append(f"abstain zh {_fmt(zh.get('abstain', (0, 0)))} en {_fmt(en.get('abstain', (0, 0)))}")
    if total["wrong"]:
        errors.append(f"wrong-attribute {len(total['wrong'])}")
    if errors:
        detail = format_report("HELD", total)
        raise AssertionError(detail + "\n" + "; ".join(errors))
    return total


class _FactRecord:
    def __init__(self, name: str, facts: list[dict]):
        self.name = name
        self.display_name = name
        self.writable = True
        self.explicit = True
        self.fact_memory = {"facts": facts}


def score_corrections(personas: list[dict], model, tok, device) -> dict:
    """英文纠正说法要落到狗的名字，问句不能被当成纠正。"""
    from memory_core.correct import propose_from_records

    by_id = {persona["id"]: persona for persona in personas}
    hits = 0
    total = 0
    false_pos = []
    misses = []
    for persona_id, spec in CORRECTIONS.items():
        persona = by_id.get(persona_id)
        if persona is None:
            continue
        facts = load_facts(persona)
        for index, fact in enumerate(facts, start=1):
            fact["id"] = f"f{index}"
        record = _FactRecord(persona_id, facts)
        for line in spec["lines"]:
            total += 1
            proposal = propose_from_records(line, [record], model=model, tok=tok, device=device)
            attr = "" if proposal is None else str(proposal.get("attr") or "")
            value = None if proposal is None else proposal.get("new_value")
            if value == spec["new"] and "dog" in attr.casefold() and "name" in attr.casefold():
                hits += 1
            else:
                misses.append((line, value, attr))
        for question, _polarity, _value in extra_questions(persona)["yesno"]:
            proposal = propose_from_records(question, [record], model=model, tok=tok, device=device)
            if proposal is not None:
                false_pos.append((question, proposal.get("new_value"), proposal.get("attr")))
    return {"hits": hits, "total": total, "misses": misses, "false": false_pos}


def assert_corrections(report: dict) -> dict:
    total = report["total"] or 1
    if report["hits"] / total < 0.90:
        raise AssertionError(f"correction {report['hits']}/{report['total']} {report['misses']}")
    if report["false"]:
        raise AssertionError(f"false corrections {report['false']}")
    return report

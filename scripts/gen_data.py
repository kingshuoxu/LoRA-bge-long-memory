"""虚构事实数据生成器。

生成基座模型绝不可能见过的虚构知识,用于纯净的长记忆测试:
- 实体名由音节池随机拼接,保证不与真实实体重合;
- 每条事实含陈述句(训练用)+ 多种问法(评估用)+ 干扰项(选择题用);
- 分批次输出 JSONL,模拟"一批批到来的新经验"。

用法: python scripts/gen_data.py --batches 5 --facts 50 --out data/
"""
import argparse
import json
import random
from pathlib import Path

# 音节池:拼凑不存在的虚构名
SYL = ["佐", "布", "雷", "塔", "尔", "维", "纳", "克", "洛", "姆",
       "萨", "丁", "格", "鲁", "佩", "奥", "辛", "达", "莫", "菲",
       "昆", "莱", "索", "巴", "特", "希", "德", "温", "珈", "缪"]

ATTRS = {
    "CEO": {
        "statement": "{e}公司的首席执行官是{v}。",
        "questions": ["{e}公司的CEO是谁?", "谁是{e}的首席执行官?",
                      "请告诉我{e}公司的首席执行官的名字。"],
        "value_kind": "person",
        "unit": "",
    },
    "成立年份": {
        "statement": "{e}公司成立于{v}年。",
        "questions": ["{e}公司是哪一年成立的?", "{e}的成立年份是什么?",
                      "请问{e}公司成立于何年?"],
        "value_kind": "year",
        "unit": "年",
    },
    "总部城市": {
        "statement": "{e}公司的总部位于{v}。",
        "questions": ["{e}公司的总部在哪里?", "{e}的总部设在哪个城市?",
                      "请说出{e}公司总部的所在地。"],
        "value_kind": "city",
        "unit": "",
    },
    "旗舰产品": {
        "statement": "{e}公司的旗舰产品是{v}。",
        "questions": ["{e}公司的旗舰产品是什么?", "{e}最出名的产品叫什么?",
                      "请告诉我{e}的旗舰产品名称。"],
        "value_kind": "product",
        "unit": "",
    },
}

# 无关常识问题:用于测门控误激活(选择性)
GENERIC_QUESTIONS = [
    "水的化学式是什么?", "一年有多少个月?", "法国的首都是哪里?",
    "地球绕太阳公转一周大约多久?", "1加1等于几?", "光合作用发生在植物的哪个器官?",
    "英语中'苹果'怎么拼?", "一周有几天?", "冰在标准大气压下多少度融化?",
    "中国的首都是哪里?", "三角形内角和是多少度?", "月亮是行星还是卫星?",
    "人体最大的器官是什么?", "光速大约是多少?", "莎士比亚是哪国人?",
    "计算机的CPU全称是什么?", "氧气在空气中大约占多少比例?",
    "太阳系最大的行星是哪颗?", "水沸腾的温度是多少摄氏度?", "中国的官方语言是什么?",
]


def make_name(rng: random.Random, lo=2, hi=4) -> str:
    return "".join(rng.choice(SYL) for _ in range(rng.randint(lo, hi)))


def make_value(rng: random.Random, kind: str, used: set) -> str:
    while True:
        if kind == "person":
            v = make_name(rng) + rng.choice(["博士", "先生", "女士"])
        elif kind == "year":
            v = str(rng.randint(1950, 2024))
        elif kind == "city":
            v = make_name(rng) + rng.choice(["市", "港", "堡"])
        elif kind == "product":
            v = make_name(rng) + "-" + str(rng.randint(100, 999))
        else:
            raise ValueError(kind)
        if v not in used:
            used.add(v)
            return v


def gen_batch(rng: random.Random, batch_id: int, n_facts: int, used_entities: set) -> list[dict]:
    facts = []
    for i in range(n_facts):
        while True:
            entity = make_name(rng)
            if entity not in used_entities:
                used_entities.add(entity)
                break
        attr = rng.choice(list(ATTRS))
        spec = ATTRS[attr]
        value = make_value(rng, spec["value_kind"], set())
        distractors = [make_value(rng, spec["value_kind"], set()) for _ in range(3)]
        choices = distractors + [value]
        rng.shuffle(choices)
        facts.append({
            "id": f"b{batch_id}-{i:03d}",
            "entity": entity,
            "attr": attr,
            "value": value,
            "statement": spec["statement"].format(e=entity, v=value),
            "qa": [{"q": q.format(e=entity), "a": value} for q in spec["questions"]],
            "mc": {
                "q": spec["questions"][0].format(e=entity),
                "choices": choices,
                "answer_idx": choices.index(value),
            },
        })
    return facts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batches", type=int, default=5)
    ap.add_argument("--facts", type=int, default=50)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, default=Path("data"))
    args = ap.parse_args()

    rng = random.Random(args.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    used_entities: set = set()
    for b in range(args.batches):
        facts = gen_batch(rng, b, args.facts, used_entities)
        path = args.out / f"batch_{b}.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for fact in facts:
                f.write(json.dumps(fact, ensure_ascii=False) + "\n")
        print(f"{path}: {len(facts)} 条")

    gq_path = args.out / "generic_questions.jsonl"
    with gq_path.open("w", encoding="utf-8") as f:
        for q in GENERIC_QUESTIONS:
            f.write(json.dumps({"q": q}, ensure_ascii=False) + "\n")
    print(f"{gq_path}: {len(GENERIC_QUESTIONS)} 条常识问题(选择性测试)")

    # 打印样例供人工检查
    sample = json.loads((args.out / "batch_0.jsonl").open(encoding="utf-8").readline())
    print("\n样例:", json.dumps(sample, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

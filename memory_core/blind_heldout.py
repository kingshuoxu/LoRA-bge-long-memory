"""用固定种子从事实模板生成没参与调参的题。

CI 读 tests/fixtures/blind_heldout_v0214.json，不在这里现抽，避免每次运行换题。
"""
from __future__ import annotations

import json
import random
from pathlib import Path

SEED = 20261113

# 多跳关系。生成时接在洗过的题后面，不重新打乱已经落盘的句子。
_CHAINS = [
    ("阿哨的主人的爸爸是谁？", "柯岚"),
    ("养阿哨的小姑娘她爸是谁？", "柯岚"),
    ("阿哨的小主人的父亲是谁？", "柯岚"),
    ("养阿哨的人她父亲守的塔有多高？", "四十二"),
    ("阿哨主人的爸爸守护的灯塔有多高？", "四十二"),
    ("白鹭塔磨透镜的师傅是哪国人？", "瑞典"),
    ("星砂盐产自哪儿？", "雾港"),
]
_CHAIN_NEVER = [
    "阿哨的主人的妈妈是谁？",
    "阿哨的主人的爸爸的妻子是谁？",
]

# 雾港书里实际记下的取值。模板只换问法，不把答案写进问句。
_TAUGHT = [
    ("白鹭塔是哪一年建的？", "1873"),
    ("那座灯塔建于哪一年？", "1873"),
    ("白鹭塔有多高？", "四十二"),
    ("塔高是多少？", "四十二"),
    ("柯小满养的海鸥叫什么？", "阿哨"),
    ("那只海鸥叫什么名字？", "阿哨"),
    ("阿哨是谁养的？", "柯小满"),
    ("阿哨的主人是谁？", "柯小满"),
    ("柯小满的父亲是谁？", "柯岚"),
    ("星砂盐是哪里的特产？", "雾港"),
    ("雾港的特产叫什么？", "星砂盐"),
    ("星砂盐什么时候开始晾？", "霜降"),
    ("海盐从哪天起晒？", "霜降"),
    ("白鹭塔哪一年改用电灯？", "1931"),
    ("透镜是哪一年通电的？", "1931"),
    ("透镜一共有多少面？", "十六"),
    ("谁打磨了透镜？", "诺丁"),
    ("诺丁是哪国人？", "瑞典"),
    ("工匠师傅是哪国人？", "瑞典"),
    ("建于1873年的塔叫什么？", "白鹭塔"),
    ("四十二米高的塔叫什么？", "白鹭塔"),
    ("柯岚的闺女叫什么？", "柯小满"),
    ("三条腿的鸟是谁养的？", "柯小满"),
    ("霜降晾的是什么？", "星砂盐"),
]

_NEVER = [
    ("柯岚是哪一年出生的？", None),
    ("柯小满的生日是哪一年？", None),
    ("白鹭塔在哪个省？", None),
    ("雾港属于哪个省？", None),
    ("星砂盐多少钱？", None),
    ("阿哨是公是母？", None),
    ("柯岚的妻子是谁？", None),
    ("诺丁的出生年是哪年？", None),
    ("雾港的市长是谁？", None),
    ("白鹭塔的灯光能照多远？", None),
    ("柯小满是男是女？", None),
    ("透镜卖多少钱？", None),
]


def generate(seed: int = SEED) -> dict:
    rng = random.Random(seed)
    taught = list(_TAUGHT)
    never = list(_NEVER)
    rng.shuffle(taught)
    rng.shuffle(never)
    taught.extend(_CHAINS)
    questions = [question for question, _gold in never]
    questions.extend(_CHAIN_NEVER)
    return {
        "seed": seed,
        "taught": [{"q": question, "gold": gold} for question, gold in taught],
        "never": questions,
    }


def dump(path: Path, seed: int = SEED) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(generate(seed), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    dump(root / "tests" / "fixtures" / "blind_heldout_v0214.json")

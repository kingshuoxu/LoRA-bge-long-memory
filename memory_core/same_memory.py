"""近义事实算同一条。标点和「我是 / 我叫」折成同一个键。"""
from __future__ import annotations

import re

REMEMBER_SIM = 0.86


def fold_statement(text: str) -> str:
    bare = str(text or "").strip().casefold()
    bare = bare.strip("。.!！？? ")
    bare = re.sub(r"[\s，,。.!！？?、]", "", bare)
    return re.sub(r"(.)\1+", r"\1", bare)


def normalize_fact_key(text: str) -> str:
    key = fold_statement(text)
    key = re.sub(r"^(用户|user|关于你)(的名字是|的姓名是|叫|是)", "我叫", key)
    if key.startswith("我的名字是"):
        key = "我叫" + key[len("我的名字是"):]
    if key.startswith("我的姓名是"):
        key = "我叫" + key[len("我的姓名是"):]
    if key.startswith("我是"):
        key = "我叫" + key[len("我是"):]
    return key


def is_same_memory(pending: str, stored: str) -> bool:
    left = normalize_fact_key(pending)
    right = normalize_fact_key(stored)
    return bool(left) and left == right

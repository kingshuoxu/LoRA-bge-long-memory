"""训练和推理共用的提示收尾。中文句子仍加上「请简短回答。」，英文句子用对应的短句。"""
from __future__ import annotations

import re

_CJK = re.compile(r"[\u4e00-\u9fff]")


def has_cjk(text: str) -> bool:
    return bool(_CJK.search(text or ""))


def system_for(user_text: str) -> str:
    if has_cjk(user_text):
        return "你是助手。"
    return "You are a helpful assistant."


def with_brief(user_text: str) -> str:
    text = (user_text or "").rstrip()
    if has_cjk(text):
        if text.endswith("请简短回答。"):
            return text
        return text + " 请简短回答。"
    if text.endswith("Answer briefly."):
        return text
    return text + " Answer briefly."

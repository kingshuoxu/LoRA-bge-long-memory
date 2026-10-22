"""界面设置。目前只存语言，放在用户数据目录的 settings.json。"""
from __future__ import annotations

import json
from pathlib import Path

from memory_core.store import atomic_write_json

LOCALES = {"zh-CN", "en"}


def load_settings(home: Path) -> dict:
    path = Path(home) / "settings.json"
    if not path.is_file():
        return {"locale": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"locale": None}
    locale = data.get("locale")
    if locale not in LOCALES:
        locale = None
    return {"locale": locale}


def save_settings(home: Path, locale: str) -> dict:
    if locale not in LOCALES:
        raise ValueError(locale)
    payload = {"locale": locale}
    atomic_write_json(Path(home) / "settings.json", payload)
    return payload

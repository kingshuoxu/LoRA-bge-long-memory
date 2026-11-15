"""界面设置。语言和更新镜像都在用户数据目录的 settings.json。"""
from __future__ import annotations

import json
from pathlib import Path

from memory_core.store import atomic_write_json

LOCALES = {"zh-CN", "en"}


def _read(home: Path) -> dict:
    path = Path(home) / "settings.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load_settings(home: Path) -> dict:
    data = _read(home)
    locale = data.get("locale")
    if locale not in LOCALES:
        locale = None
    url = data.get("update_url")
    if not isinstance(url, str):
        url = ""
    return {"locale": locale, "update_url": url.strip()}


def save_settings(home: Path, locale: str | None = None, update_url: str | None = None) -> dict:
    """只改传入的字段。保存语言时不会把更新镜像清掉。"""
    data = _read(home)
    if locale is not None:
        if locale not in LOCALES:
            raise ValueError(locale)
        data["locale"] = locale
    if update_url is not None:
        data["update_url"] = str(update_url).strip()
    atomic_write_json(Path(home) / "settings.json", data)
    return load_settings(home)

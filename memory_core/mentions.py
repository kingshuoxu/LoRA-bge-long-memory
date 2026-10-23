"""记下对话里提到过、但未必抽成事实的主语。

只记非问句。问句里的「中国」不会因此挡住「中国的首都是哪里」。
"""
from __future__ import annotations

import json
from pathlib import Path

from memory_core.extract import subject_names


def _path(home: Path) -> Path:
    return Path(home) / "mentions.json"


def load_mentions(home: Path) -> list[str]:
    path = _path(home)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [str(item) for item in data if str(item).strip()]


def remember_statement(home: Path, text: str) -> list[str]:
    names = subject_names(text)
    if not names:
        return load_mentions(home)
    current = load_mentions(home)
    for name in names:
        if name not in current:
            current.append(name)
    path = _path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return current

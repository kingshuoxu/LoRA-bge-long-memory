"""把旧目录里的对话、专家和模型并进现在的用户数据目录。

安装包更新只替换程序本身。这里在第一次改用 Electron userData 时把原来的
家目录和模型缓存搬过去，避免用户重下模型或丢掉已经记住的事实。
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from memory_core.models_mgr import models_ready

_HOME_NAMES = (
    "conversations.sqlite",
    "conversations.sqlite-wal",
    "conversations.sqlite-shm",
    "experts",
    "jobs",
    "previews",
    "settings.json",
    "deleted_experts.json",
)


def legacy_home() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "lora-bge-memory"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "lora-bge-memory"
    return Path.home() / ".local" / "share" / "lora-bge-memory"


def legacy_models() -> Path:
    return Path.home() / ".cache" / "lora-bge-memory" / "models"


def _same(left: Path, right: Path) -> bool:
    try:
        return left.expanduser().resolve() == right.expanduser().resolve()
    except OSError:
        return str(left) == str(right)


def _move_into(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return
    try:
        os.rename(source, target)
        return
    except OSError:
        pass
    if source.is_dir():
        shutil.copytree(source, target)
    else:
        shutil.copy2(source, target)


def _checkpoint_sqlite(path: Path) -> None:
    """把还在 WAL 里的对话写进主库，再搬走。打不开就留给后面的 -wal 文件一起搬。"""
    import sqlite3

    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.commit()
    finally:
        conn.close()


def migrate_legacy(home: Path, models: Path, source_home: Path | None = None) -> None:
    """目标里已经有的文件不动。只补上缺的对话、专家和模型。"""
    home = Path(home)
    models = Path(models)
    source_home = Path(source_home) if source_home is not None else legacy_home()
    database = source_home / "conversations.sqlite"
    if database.is_file():
        try:
            _checkpoint_sqlite(database)
        except Exception:
            pass
    if not _same(source_home, home) and source_home.is_dir():
        for name in _HOME_NAMES:
            source = source_home / name
            if source.exists():
                _move_into(source, home / name)
    source_models = legacy_models()
    if _same(source_models, models) or models_ready(models) or not models_ready(source_models):
        return
    if not models.exists():
        try:
            models.parent.mkdir(parents=True, exist_ok=True)
            os.rename(source_models, models)
            return
        except OSError:
            pass
    if source_models.is_dir():
        for child in source_models.iterdir():
            _move_into(child, models / child.name)

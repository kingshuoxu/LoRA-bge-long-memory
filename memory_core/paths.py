"""仓库根、安装包内代码目录、用户数据与模型缓存路径。"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def bundle_root() -> Path:
    """memory_core 的上一级。仓库里是仓库根；安装包里是 resources/app。"""
    return Path(__file__).resolve().parents[1]


def scripts_dir() -> Path:
    return bundle_root() / "scripts"


def ensure_scripts_path() -> Path:
    scripts = scripts_dir()
    text = str(scripts)
    if text not in sys.path:
        sys.path.insert(0, text)
    return scripts


def repo_root() -> Path | None:
    """只有完整研究仓库才返回根目录。安装包里的 app 目录没有 README。"""
    root = bundle_root()
    if (root / "README.md").is_file() and (root / "scripts" / "router.py").is_file():
        return root
    return None


def default_models_dir() -> Path:
    env = os.environ.get("LORA_MEMORY_MODELS")
    if env:
        return Path(env).expanduser()
    root = repo_root()
    if root is not None and (root / "models").is_dir():
        return root / "models"
    return Path.home() / ".cache" / "lora-bge-memory" / "models"


def default_home() -> Path:
    env = os.environ.get("LORA_MEMORY_HOME")
    if env:
        return Path(env).expanduser()
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "lora-bge-memory"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "lora-bge-memory"
    return Path.home() / ".local" / "share" / "lora-bge-memory"


def default_repo_experts() -> Path | None:
    env = os.environ.get("LORA_MEMORY_REPO_EXPERTS")
    if env:
        path = Path(env).expanduser()
        return path if (path / "router.jsonl").is_file() else None
    root = repo_root()
    if root is None:
        return None
    path = root / "experts"
    if (path / "router.jsonl").is_file():
        return path
    return None


QWEN_DIRNAME = "Qwen2.5-0.5B-Instruct"
BGE_DIRNAME = "bge-small-zh-v1.5"

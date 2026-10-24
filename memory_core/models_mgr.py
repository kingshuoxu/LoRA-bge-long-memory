"""首次运行下载基座和 bge。体积在文档里按实测填写。"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from memory_core.paths import BGE_DIRNAME, QWEN_DIRNAME

# 忽略的是不参与推理的重复权重。bge 同时有 bin 和 safetensors 时只留 safetensors。
_IGNORE = [
    "*.msgpack",
    "*.h5",
    "flax_model*",
    "tf_model*",
    "onnx/*",
    "*.onnx",
    "*.ot",
    "openvino/*",
    "pytorch_model.bin",
]

_SPECS = (
    (QWEN_DIRNAME, "Qwen/Qwen2.5-0.5B-Instruct", "model.safetensors", 500_000_000),
    (BGE_DIRNAME, "BAAI/bge-small-zh-v1.5", "model.safetensors", 10_000_000),
)


def _weight_ok(models_dir: Path, dirname: str, filename: str, min_bytes: int) -> bool:
    path = models_dir / dirname / filename
    return path.is_file() and path.stat().st_size >= min_bytes


def models_ready(models_dir: Path) -> bool:
    return all(_weight_ok(models_dir, dirname, filename, minimum) for dirname, _, filename, minimum in _SPECS)


def qwen_path(models_dir: Path) -> Path:
    return models_dir / QWEN_DIRNAME


def bge_path(models_dir: Path) -> Path:
    return models_dir / BGE_DIRNAME


def status_path(models_dir: Path) -> Path:
    return models_dir / "download_status.json"


def read_status(models_dir: Path) -> dict:
    path = status_path(models_dir)
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    if models_ready(models_dir):
        return {"state": "ready", "detail": ""}
    return {"state": "missing", "detail": ""}


def _write_status(models_dir: Path, state: str, detail: str = "") -> None:
    models_dir.mkdir(parents=True, exist_ok=True)
    payload = {"state": state, "detail": detail}
    path = status_path(models_dir)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


_lock = threading.Lock()


def ensure_models(models_dir: Path) -> None:
    """阻塞直到两个模型都在本地。huggingface_hub 会接着未下完的文件继续。"""
    models_dir = Path(models_dir)
    if models_ready(models_dir):
        _write_status(models_dir, "ready", "")
        return
    with _lock:
        if models_ready(models_dir):
            _write_status(models_dir, "ready", "")
            return
        os_env_setup()
        from huggingface_hub import snapshot_download

        try:
            for dirname, repo, filename, minimum in _SPECS:
                if _weight_ok(models_dir, dirname, filename, minimum):
                    continue
                _write_status(models_dir, "downloading", repo)
                snapshot_download(
                    repo,
                    local_dir=str(models_dir / dirname),
                    ignore_patterns=_IGNORE,
                )
            if not models_ready(models_dir):
                raise RuntimeError("模型文件不完整")
            _write_status(models_dir, "ready", "")
        except Exception as exc:
            _write_status(models_dir, "error", str(exc))
            raise


def os_env_setup() -> None:
    import os

    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")


def model_sizes(models_dir: Path) -> dict[str, int]:
    sizes = {}
    for dirname, _, _, _ in _SPECS:
        root = models_dir / dirname
        total = 0
        if root.is_dir():
            for path in root.rglob("*"):
                if path.is_file():
                    total += path.stat().st_size
        sizes[dirname] = total
    return sizes

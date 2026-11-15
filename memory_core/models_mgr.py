"""首次运行下载基座和 bge。体积在文档里按实测填写。"""
from __future__ import annotations

import json
import os
import threading
import time
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

# 只用来画下载进度，不参与「模型是否可用」的判断。真实体积更大时进度停在 99%，直到写完。
_PROGRESS_TOTAL = {
    "Qwen/Qwen2.5-0.5B-Instruct": 1_000_000_000,
    "BAAI/bge-small-zh-v1.5": 100_000_000,
}


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


def _write_status(models_dir: Path, state: str, detail: str = "", **extra) -> None:
    payload = {"state": state, "detail": detail}
    payload.update(extra)
    _write_status_payload(models_dir, payload)


def _write_status_payload(models_dir: Path, payload: dict) -> None:
    models_dir.mkdir(parents=True, exist_ok=True)
    path = status_path(models_dir)
    text = json.dumps(payload, ensure_ascii=False)
    delay = 0.05
    last: Exception | None = None
    for attempt in range(6):
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
        try:
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, path)
            return
        except PermissionError as exc:
            last = exc
            time.sleep(delay)
            delay = min(delay * 2, 0.4)
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
    if last:
        raise last


def _friendly_file(name: str) -> str:
    if name.endswith(".incomplete"):
        return name[: -len(".incomplete")]
    return name


def measure_model_dir(root: Path) -> tuple[int, str]:
    """目录里已经落到盘上的字节，以及正在写的那个文件名。"""
    downloaded = 0
    incomplete = ""
    newest_name = ""
    newest = -1.0
    if not root.is_dir():
        return 0, ""
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        downloaded += stat.st_size
        if path.name.endswith(".incomplete"):
            incomplete = _friendly_file(path.name)
        elif stat.st_mtime >= newest:
            newest = stat.st_mtime
            newest_name = path.name
    return downloaded, incomplete or newest_name


def publish_download_progress(models_dir: Path, repo: str, current_file: str = "") -> dict:
    """把两个模型目录的体积写成下载进度。界面按 percent、downloaded、total、file 来画。"""
    downloaded = 0
    scanned = ""
    for dirname, repo_id, _, _ in _SPECS:
        size, name = measure_model_dir(Path(models_dir) / dirname)
        downloaded += size
        if repo_id == repo and name:
            scanned = name
    total = sum(_PROGRESS_TOTAL.get(repo_id, 0) for _, repo_id, _, _ in _SPECS)
    if total and downloaded >= total:
        total = downloaded + 1
    percent = int(downloaded * 100 / total) if total else 0
    payload = {
        "state": "downloading",
        "detail": repo,
        "file": current_file or scanned,
        "downloaded": downloaded,
        "total": total,
        "percent": max(0, min(99, percent)),
    }
    _write_status_payload(Path(models_dir), payload)
    return payload


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
                current = {"name": ""}
                publish_download_progress(models_dir, repo, current["name"])
                stop = threading.Event()

                def watch(repo_name: str = repo, holder: dict = current) -> None:
                    while not stop.wait(0.4):
                        try:
                            publish_download_progress(models_dir, repo_name, holder["name"])
                        except OSError:
                            pass

                watcher = threading.Thread(target=watch, name=f"download-{dirname}", daemon=True)
                watcher.start()
                try:
                    kwargs = {
                        "local_dir": str(models_dir / dirname),
                        "ignore_patterns": _IGNORE,
                    }
                    bar = _byte_progress(current)
                    if bar is not None:
                        kwargs["tqdm_class"] = bar
                    try:
                        snapshot_download(repo, **kwargs)
                    except TypeError:
                        kwargs.pop("tqdm_class", None)
                        snapshot_download(repo, **kwargs)
                finally:
                    stop.set()
                    watcher.join(timeout=1)
            if not models_ready(models_dir):
                raise RuntimeError("模型文件不完整")
            _write_status(models_dir, "ready", "")
        except Exception as exc:
            _write_status(models_dir, "error", str(exc))
            raise


def _byte_progress(holder: dict):
    """huggingface 每写一块就记下当前文件名。没有这层进度条时仍靠目录体积。"""
    try:
        from huggingface_hub.utils import tqdm as hf_tqdm
    except Exception:
        return None

    class _Bar(hf_tqdm):
        def update(self, n=1):
            result = super().update(n)
            if getattr(self, "unit", None) == "B":
                desc = str(getattr(self, "desc", "") or "").strip()
                if desc:
                    holder["name"] = desc
            return result

    return _Bar


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

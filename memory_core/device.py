"""训练 / 推理设备。CPU 上强制 float32；有 CUDA 或 MPS 时训练仍用 float32。"""
from __future__ import annotations

import os

import torch


def has_cuda() -> bool:
    return torch.cuda.is_available()


def has_mps() -> bool:
    backend = getattr(torch.backends, "mps", None)
    return bool(backend is not None and backend.is_available())


def pick_device(prefer: str | None = None) -> torch.device:
    """prefer: auto | cpu | cuda | mps。auto 的顺序是 CUDA、MPS、CPU。

    DirectML 不走这里：研究记录里它的前向数值和 CPU 对不上，不能用来写记忆。
    """
    choice = (prefer or os.environ.get("LORA_MEMORY_DEVICE") or "auto").lower()
    if choice == "cpu":
        device = torch.device("cpu")
    elif choice == "cuda":
        if not has_cuda():
            raise RuntimeError("指定了 CUDA，但当前 PyTorch 检测不到可用 GPU")
        device = torch.device("cuda")
    elif choice == "mps":
        if not has_mps():
            raise RuntimeError("指定了 MPS，但当前 PyTorch 不可用")
        device = torch.device("mps")
    elif choice == "auto":
        if has_cuda():
            device = torch.device("cuda")
        elif has_mps():
            device = torch.device("mps")
        else:
            device = torch.device("cpu")
    else:
        raise RuntimeError(f"未知设备 {choice}")
    if device.type == "cpu":
        torch.set_num_threads(max(1, os.cpu_count() or 1))
    return device


def train_dtype(device: torch.device) -> torch.dtype:
    """CPU 必须 float32。CUDA / MPS 训练也用 float32，和 scripts/train_expert.py 一致。"""
    del device
    return torch.float32


def infer_dtype(device: torch.device) -> torch.dtype:
    if device.type == "cpu":
        return torch.float32
    if device.type == "cuda":
        return torch.float16
    return torch.float32

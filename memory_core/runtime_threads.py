"""每个进程只用有限的计算线程。

环境变量已经设好就照它来。没有设时，后端和训练各用 2 条，避免一台笔记本被占满。
这些变量要在加载 OpenBLAS / MKL 之前写上，所以包一导入就调用。
"""
from __future__ import annotations

import os

_KEYS = (
    "LORA_MEMORY_THREADS",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
)
_PROPAGATE = (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)
_applied = False


def _positive(raw: str | None) -> int | None:
    text = (raw or "").strip()
    if not text or not text.isdigit():
        return None
    value = int(text)
    return value if value >= 1 else None


def thread_budget() -> int:
    """调用方传入的线程数优先。都没写时，单进程默认 2。"""
    for key in _KEYS:
        found = _positive(os.environ.get(key))
        if found is not None:
            return found
    return min(2, os.cpu_count() or 1)


def configure_process_threads() -> int:
    """还没写的 BLAS 变量补成同一个上限。已经写过的不改。"""
    budget = thread_budget()
    for key in _PROPAGATE:
        os.environ.setdefault(key, str(budget))
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    return budget


def apply_torch_threads() -> int:
    """torch 的算子线程跟上面的上限走，线程之间不再再开一组。"""
    global _applied
    budget = configure_process_threads()
    import torch

    interop = _positive(os.environ.get("LORA_MEMORY_INTEROP_THREADS")) or 1
    if not _applied:
        try:
            torch.set_num_interop_threads(interop)
        except RuntimeError:
            pass
        _applied = True
    torch.set_num_threads(budget)
    return budget

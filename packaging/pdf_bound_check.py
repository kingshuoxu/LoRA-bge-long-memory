"""打包后的运行时：线程不超过传入的上限，小 PDF 在时限内导入完成。"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memory_core.runtime_threads import apply_torch_threads, thread_budget


def main() -> None:
    budget = apply_torch_threads()
    import torch

    got = torch.get_num_threads()
    print(f"THREADS {got} budget {budget}", flush=True)
    if got > budget:
        raise SystemExit(f"计算线程 {got} 超过上限 {budget}")
    book = Path(os.environ.get("LORA_MEMORY_BOOK") or ROOT / "tests/fixtures/wugang/wugang_chrome.pdf")
    if not book.is_file():
        raise SystemExit(f"找不到 PDF: {book}")
    bound = float(os.environ.get("LORA_MEMORY_DOC_BOUND") or "240")
    os.environ.setdefault("LORA_MEMORY_DOC_SECONDS", "180")
    from memory_core.service import MemoryService

    home = Path(os.environ.get("LORA_MEMORY_HOME") or "/tmp/yingyu-pdf-bound")
    models = Path(os.environ.get("LORA_MEMORY_MODELS") or "/tmp/yingyu-models")
    service = MemoryService(home=home, models_dir=models, device="cpu", use_repo_experts=False)
    started = time.monotonic()
    service.start_document_import(str(book))
    status = {"phase": "parse"}
    while time.monotonic() - started < bound:
        status = service.document_status()
        phase = status.get("phase")
        print(f"[pdf] {phase} {status.get('percent')} {status.get('message') or ''}", flush=True)
        if phase in {"done", "error", "cancelled"}:
            break
        time.sleep(1)
    else:
        raise SystemExit(f"PDF 导入超过 {bound:.0f} 秒，停在 {status.get('phase')} {status.get('percent')}")
    elapsed = time.monotonic() - started
    print(f"PDF_IMPORT {status.get('phase')} {elapsed:.1f}s", flush=True)
    if status.get("phase") != "done":
        raise SystemExit(f"导入没有完成: {status}")
    if not service.list_documents():
        raise SystemExit("导入结束后文档列表仍是空的")
    print("PDF_BOUND_OK", flush=True)


if __name__ == "__main__":
    main()

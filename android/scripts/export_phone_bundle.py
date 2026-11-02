#!/usr/bin/env python3
"""把现有专家收成手机能读的目录:GGUF LoRA、fact_memory、key_texts、float32 路由键和事实向量。"""
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from router import load_fact_memory, load_router  # noqa: E402


def main() -> None:
    out = ROOT / "android" / "out" / "phone-bundle"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    gguf = ROOT / "android" / "out" / "gguf"
    memory = load_fact_memory(ROOT / "experts")
    if memory is None:
        raise SystemExit("没有 fact_memory")
    # 事实向量按专家切开。load_fact_memory 把所有专家串在一起,顺序与 experts/router.jsonl 一致。
    cursor = 0
    records = []
    for entry in load_router(ROOT / "experts" / "router.jsonl"):
        name = entry["expert"]
        src = ROOT / "experts" / name
        dest = out / name
        dest.mkdir()
        adapter = gguf / f"{name}.gguf"
        if not adapter.exists():
            raise SystemExit(f"先转换 {adapter}")
        shutil.copy(adapter, dest / "adapter.gguf")
        shutil.copy(src / "fact_memory.json", dest / "fact_memory.json")
        shutil.copy(src / "key_texts.json", dest / "key_texts.json")
        key = torch.load(entry["key_path"], weights_only=True).contiguous().float().numpy()
        key.tofile(dest / "router_key.f32")
        facts = json.loads((src / "fact_memory.json").read_text(encoding="utf-8"))
        n = 0
        for fact in facts:
            n += 1 + len(fact.get("questions") or [])
        block = memory._vec[cursor:cursor + n].contiguous().float().numpy()
        if block.shape[0] != n:
            raise SystemExit(f"{name} 事实向量行数 {block.shape[0]} != {n}")
        block.tofile(dest / "fact_vectors.f32")
        cursor += n
        records.append({
            "expert": name,
            "batch": entry["batch"],
            "n_facts": entry["n_facts"],
            "rank": entry.get("rank", 32),
            "key_path": f"experts/{name}/router_key.f32",
            "weight": f"experts/{name}/adapter.gguf",
            "key_format": "float32",
            "dim": int(key.shape[1]),
        })
    if cursor != memory._vec.shape[0]:
        raise SystemExit(f"事实向量没用完: {cursor} / {memory._vec.shape[0]}")
    (out / "router.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    (out / "fact_gate.json").write_text((ROOT / "experts" / "fact_gate.json").read_text(encoding="utf-8"), encoding="utf-8")
    print(f"写出 {out}  专家 {len(records)}  事实向量行 {cursor}")


if __name__ == "__main__":
    main()

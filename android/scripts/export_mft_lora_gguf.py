#!/usr/bin/env python3
"""把 MobileFineTuner 的 lora_weights.bin 写成 llama.cpp 能挂的 GGUF LoRA。

bin 里每层按 gate、up、down 的顺序存 A 再存 B。A 是 [in, rank],B 是 [rank, out],
行优先,训练时的缩放是 alpha/rank,权重本身不乘缩放。
llama.cpp 读到的 ggml 形状是 lora_a [in, rank]、lora_b [rank, out],数据按 ne[0] 连续,
对应 PEFT 的 lora_A [rank, in] 和 lora_B [out, rank]。所以这里把矩阵转置后再写入。
"""
import argparse
import json
import struct
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def load_bin(path: Path, manifest: dict) -> list[tuple[str, np.ndarray]]:
    data = path.read_bytes()
    off = 0
    (n,) = struct.unpack_from("<i", data, off)
    off += 4
    tensors = manifest["tensors"]
    if n != len(tensors):
        raise SystemExit(f"参数个数 {n} 和清单 {len(tensors)} 不一致")
    out = []
    for spec in tensors:
        (ndim,) = struct.unpack_from("<i", data, off)
        off += 4
        dims = struct.unpack_from("<" + "q" * ndim, data, off)
        off += 8 * ndim
        if list(dims) != spec["shape"]:
            raise SystemExit(f"{spec['name']} 形状 {dims} != {spec['shape']}")
        numel = 1
        for d in dims:
            numel *= d
        arr = np.frombuffer(data, dtype="<f4", count=numel, offset=off).reshape(dims).copy()
        off += 4 * numel
        out.append((spec["name"], arr))
    if off != len(data):
        raise SystemExit(f"文件没有读完,剩下 {len(data) - off} 字节")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bin", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--name", default="mft-expert")
    args = ap.parse_args()
    import gguf

    manifest = json.loads(args.manifest.read_text())
    pairs = load_bin(args.bin, manifest)
    alpha = float(manifest["alpha"])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    writer = gguf.GGUFWriter(args.out, "qwen2")
    writer.add_type("adapter")
    writer.add_string("adapter.type", "lora")
    writer.add_string("general.name", args.name)
    writer.add_float32("adapter.lora.alpha", alpha)
    writer.add_quantization_version(2)
    for name, arr in pairs:
        # lora_A / lora_B -> lora_a / lora_b, and transpose into PEFT layout.
        gguf_name = name.replace(".lora_A", ".lora_a").replace(".lora_B", ".lora_b")
        writer.add_tensor(gguf_name, np.ascontiguousarray(arr.T.astype(np.float16)))
    writer.write_header_to_file()
    writer.write_kv_data_to_file()
    writer.write_tensors_to_file()
    writer.close()
    print(f"写出 {args.out} ({args.out.stat().st_size} 字节, alpha={alpha}, tensors={len(pairs)})")


if __name__ == "__main__":
    main()

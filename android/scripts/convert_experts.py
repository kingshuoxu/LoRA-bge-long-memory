#!/usr/bin/env python3
"""把现有 PEFT 专家转成 GGUF LoRA,供 llama-cli --lora 挂载。

基座量化用官方 Qwen2.5-0.5B-Instruct Q8_0(见 fetch_base_gguf.sh)。
适配器默认 f16:rank 32 的 FFN LoRA 大约几十 MB,和 fp32 safetensors 比大约一半。
转换脚本钉在 ggml-org/llama.cpp 的 b7349(和 QVAC 发布号相同,提交不同)。
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LLAMA_CPP_COMMIT = "4df6e859e92dac52536f735785bb9e0a3bc63e2b"  # ggml-org/llama.cpp tag b7349


def ensure_llama_cpp(dest: Path) -> Path:
    script = dest / "convert_lora_to_gguf.py"
    if script.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        subprocess.run(["git", "-C", str(dest), "fetch", "--depth", "1", "origin", LLAMA_CPP_COMMIT], check=True)
        subprocess.run(["git", "-C", str(dest), "checkout", LLAMA_CPP_COMMIT], check=True)
    else:
        subprocess.run([
            "git", "clone", "--depth", "1", "--branch", "b7349",
            "https://github.com/ggml-org/llama.cpp.git", str(dest),
        ], check=True)
    head = subprocess.check_output(["git", "-C", str(dest), "rev-parse", "HEAD"], text=True).strip()
    if not head.startswith(LLAMA_CPP_COMMIT[:12]):
        raise SystemExit(f"llama.cpp 版本不是 b7349: {head}")
    return dest


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--experts", type=Path, default=ROOT / "experts")
    ap.add_argument("--base", type=Path, default=ROOT / "models" / "Qwen2.5-0.5B-Instruct")
    ap.add_argument("--out", type=Path, default=ROOT / "android" / "out" / "gguf")
    ap.add_argument("--which", default="0,1,2,3,4", help="专家编号,逗号分隔")
    ap.add_argument("--outtype", default="f16", choices=["f16", "f32", "q8_0"])
    ap.add_argument("--llama-cpp", type=Path, default=Path(os.environ.get("LLAMA_CPP", "/tmp/llama.cpp-b7349")))
    args = ap.parse_args()
    if not (args.base / "config.json").exists():
        raise SystemExit(f"缺少基座配置 {args.base}。先按 README 下载 Qwen2.5-0.5B-Instruct。")
    src = ensure_llama_cpp(args.llama_cpp)
    args.out.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(src / "gguf-py") + os.pathsep + env.get("PYTHONPATH", "")
    py = os.environ.get("PYTHON", sys.executable)
    for num in [x.strip() for x in args.which.split(",") if x.strip()]:
        lora = args.experts / f"expert_{num}"
        weights = lora / "adapter_model.safetensors"
        if not weights.exists() or weights.stat().st_size < 1000:
            raise SystemExit(f"{weights} 不存在或只是 Git LFS 指针。在仓库根目录执行 git lfs pull --include 'experts/**'")
        outfile = args.out / f"expert_{num}.gguf"
        cmd = [
            py, str(src / "convert_lora_to_gguf.py"),
            "--base", str(args.base),
            "--outtype", args.outtype,
            "--outfile", str(outfile),
            str(lora),
        ]
        print(" ".join(cmd), flush=True)
        subprocess.run(cmd, check=True, env=env)
        print(f"写出 {outfile} ({outfile.stat().st_size} 字节)")


if __name__ == "__main__":
    main()

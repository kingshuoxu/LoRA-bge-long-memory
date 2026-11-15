"""启动仓库里的 backend.server。

CI 的系统 python 只装了测试用的 pypdf。权重在 packaging/runtime 里，
所以服务进程要用那份解释器，否则一启动就因缺少 torch 退出。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


def interpreter(root: Path) -> tuple[str, dict[str, str]]:
    runtime = root / "packaging" / "runtime"
    py = runtime / "python.exe" if os.name == "nt" else runtime / "bin" / "python3"
    extra: dict[str, str] = {}
    if py.is_file():
        lib = runtime / "lib"
        if lib.is_dir():
            prev = os.environ.get("LD_LIBRARY_PATH", "")
            extra["LD_LIBRARY_PATH"] = str(lib) + (os.pathsep + prev if prev else "")
        return str(py), extra
    return sys.executable, {}


def run_until_ready(root: Path, env: dict[str, str], timeout: float) -> tuple[subprocess.Popen, str, str]:
    """等到 LORA_MEMORY_READY。返回进程、端口、已经读到的输出。"""
    py, extra = interpreter(root)
    merged = dict(env)
    merged.update(extra)
    proc = subprocess.Popen(
        [py, "-m", "backend.server"],
        cwd=str(root),
        env=merged,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert proc.stdout is not None
    lines: list[str] = []
    port = ""
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                break
            continue
        lines.append(line)
        if "LORA_MEMORY_READY port=" in line:
            port = line.strip().split("port=", 1)[1].strip()
            break
    return proc, port, "".join(lines)

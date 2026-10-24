"""下载可重定位的 CPython，并装上 CPU（macOS 为官方含 MPS 的）PyTorch。

输出目录：packaging/runtime。electron-builder 会把它打进安装包。
"""
from __future__ import annotations

import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

def _utf8_stdio() -> None:
    """Windows 上的 GitHub runner 默认是 cp1252，中文日志会直接让构建退出。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_utf8_stdio()

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "packaging" / "runtime"
CACHE = ROOT / "packaging" / "cache"
RELEASE = "20261021"
PY_VER = "3.12.15"


def asset_name() -> str:
    system = sys.platform
    machine = platform.machine().lower()
    if system.startswith("linux") and machine in {"x86_64", "amd64"}:
        triple = "x86_64-unknown-linux-gnu"
    elif system.startswith("linux") and machine in {"aarch64", "arm64"}:
        triple = "aarch64-unknown-linux-gnu"
    elif system == "darwin" and machine in {"arm64", "aarch64"}:
        triple = "aarch64-apple-darwin"
    elif system == "darwin" and machine == "x86_64":
        triple = "x86_64-apple-darwin"
    elif system == "win32" and machine.lower() in {"amd64", "x86_64"}:
        triple = "x86_64-pc-windows-msvc"
    else:
        raise SystemExit(f"没有对应的独立 Python 构建：{system} {machine}")
    return f"cpython-{PY_VER}+{RELEASE}-{triple}-install_only.tar.gz"


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 1_000_000:
        print(f"已有缓存 {dest}", flush=True)
        return
    print(f"下载 {url}", flush=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=120) as response, tmp.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    tmp.replace(dest)


def python_bin(runtime: Path) -> Path:
    if sys.platform == "win32":
        return runtime / "python.exe"
    return runtime / "bin" / "python3"


def main() -> None:
    name = asset_name()
    url = f"https://github.com/astral-sh/python-build-standalone/releases/download/{RELEASE}/{name}"
    archive = CACHE / name
    download(url, archive)
    if OUT.exists():
        shutil.rmtree(OUT)
    extract_root = CACHE / "extract"
    if extract_root.exists():
        shutil.rmtree(extract_root)
    extract_root.mkdir(parents=True)
    print(f"解压 {archive.name}", flush=True)
    with tarfile.open(archive, "r:gz") as tar:
        try:
            tar.extractall(extract_root, filter="data")
        except TypeError:
            tar.extractall(extract_root)
    extracted = extract_root / "python"
    if not extracted.is_dir():
        raise SystemExit("压缩包里没有 python/ 目录")
    shutil.move(str(extracted), str(OUT))
    py = python_bin(OUT)
    if not py.is_file():
        raise SystemExit(f"找不到解释器 {py}")
    subprocess.check_call([str(py), "-m", "pip", "install", "--upgrade", "pip"])
    if sys.platform == "darwin":
        torch_cmd = [str(py), "-m", "pip", "install", "--no-cache-dir", "torch"]
    else:
        torch_cmd = [
            str(py), "-m", "pip", "install", "--no-cache-dir", "torch",
            "--index-url", "https://download.pytorch.org/whl/cpu",
        ]
    print("安装 torch", flush=True)
    subprocess.check_call(torch_cmd)
    print("安装其余依赖", flush=True)
    subprocess.check_call([
        str(py), "-m", "pip", "install", "--no-cache-dir",
        "-r", str(ROOT / "requirements-desktop.txt"),
    ])
    for tests in OUT.rglob("test"):
        if tests.is_dir() and tests.name == "test" and tests.parent.name.startswith("python"):
            shutil.rmtree(tests, ignore_errors=True)
    subprocess.call([str(py), "-m", "pip", "cache", "purge"])
    subprocess.check_call([
        str(py), "-c",
        "import torch,transformers,peft; print(torch.__version__, transformers.__version__, peft.__version__)",
    ])
    print(f"runtime -> {OUT}", flush=True)


if __name__ == "__main__":
    main()

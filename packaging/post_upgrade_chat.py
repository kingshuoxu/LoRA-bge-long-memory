"""0.2.7 的用户目录在同一次进程里迁移之后，立刻用 HTTP 问一句日常对话。

预热线程和第一问会同时加载基座。权重必须先落到 cpu，不能停在 meta 上。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    models = Path(os.environ.get("LORA_MEMORY_MODELS") or root / "model-cache")
    if not (models / "Qwen2.5-0.5B-Instruct").is_dir() and not any(models.glob("**/config.json")):
        sys.exit(f"找不到模型目录 {models}")
    work = Path(os.environ.get("UPGRADE_CHAT_HOME") or Path("/tmp") / "yingyu-upgrade-chat")
    if work.exists():
        import shutil
        shutil.rmtree(work)
    data = work / "config" / "lora-bge-memory"
    expert = data / "experts" / "expert_1000"
    expert.mkdir(parents=True)
    (expert / "fact_memory.json").write_text(json.dumps({
        "expert": "expert_1000",
        "display_name": "用户/徐金朔",
        "entities": ["用户"],
        "facts": [{
            "id": "f1",
            "entity": "用户",
            "attr": "名字",
            "value": "徐金朔",
            "statement": "用户叫徐金朔。",
        }],
    }, ensure_ascii=False), encoding="utf-8")
    env = os.environ.copy()
    env.update({
        "LORA_MEMORY_HOME": str(data),
        "LORA_MEMORY_MODELS": str(models),
        "LORA_MEMORY_DEVICE": "cpu",
        "LORA_MEMORY_PORT": "0",
        "PYTHONPATH": str(root),
        "PYTHONUNBUFFERED": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
    })
    proc = subprocess.Popen(
        [sys.executable, "-m", "backend.server"],
        cwd=str(root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    port = ""
    deadline = time.time() + 60
    assert proc.stdout is not None
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                sys.exit(f"服务提前退出 {proc.returncode}")
            continue
        if "LORA_MEMORY_READY port=" in line:
            port = line.strip().split("port=", 1)[1]
            break
    if not port:
        proc.kill()
        sys.exit("服务没有就绪")
    base = f"http://127.0.0.1:{port}/api"

    def post(path: str, payload: dict) -> tuple[int, dict]:
        req = urllib.request.Request(
            base + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as res:
                return res.status, json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return exc.code, {"error": body}

    status, created = post("/conversations", {"title": "升级后"})
    if status != 200 or not created.get("id"):
        proc.kill()
        sys.exit(f"建对话失败 {status} {created}")
    status, reply = post(f"/conversations/{created['id']}/messages", {"content": "帮我写一句今天的问候"})
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    text = ""
    if isinstance(reply, dict):
        text = str((reply.get("assistant") or {}).get("content") or reply.get("error") or "")
    if status != 200 or not text.strip() or "meta" in text.lower():
        sys.exit(f"升级后的同一次会话没有答出来 {status} {text}")
    print("UPGRADE_CHAT_OK", status, text[:80])


if __name__ == "__main__":
    main()

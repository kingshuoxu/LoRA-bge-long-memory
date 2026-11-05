"""用 0.2.16 的服务进程连开两次，确认 0.2.14 的清理只跑一遍。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from server_proc import run_until_ready


LEGIT = [
    "我的职业是翻译",
    "我是一名翻译",
    "她喜欢别人推荐的书",
    "我做产品推荐工作",
    "我喜欢写诗",
]
JUNK = [
    "写一首关于秋天的四行小诗",
    "帮我翻译这句话",
    "给我推荐几本书",
]


def _seed(home: Path, version: str) -> None:
    expert = home / "experts" / "expert_9"
    expert.mkdir(parents=True)
    facts = [{"entity": "我", "statement": text, "value": text, "app_version": version} for text in LEGIT + JUNK]
    (expert / "fact_memory.json").write_text(json.dumps({
        "app_version": version,
        "entities": ["我"],
        "facts": facts,
    }, ensure_ascii=False), encoding="utf-8")
    (home / "app-version.json").write_text(json.dumps({"version": version}), encoding="utf-8")
    queued = home / "documents" / "doc1"
    queued.mkdir(parents=True)
    (queued / "queued.json").write_text(json.dumps(["工匠的名字", "啥名", "那个瑞典来…", "我的职业是翻译"]), encoding="utf-8")


def _launch(root: Path, home: Path, models: Path) -> None:
    env = os.environ.copy()
    env.update({
        "LORA_MEMORY_HOME": str(home),
        "LORA_MEMORY_MODELS": str(models),
        "LORA_MEMORY_DEVICE": "cpu",
        "LORA_MEMORY_PORT": "0",
        "PYTHONPATH": str(root),
        "PYTHONUNBUFFERED": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
    })
    proc, port, log = run_until_ready(root, env, 90)
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    if not port:
        sys.exit(f"服务没有起来\n{log}")


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    models = Path(os.environ.get("LORA_MEMORY_MODELS") or "/tmp/yingyu-models")
    work = Path("/tmp/yingyu-migrate-0214")
    if work.exists():
        import shutil
        shutil.rmtree(work)
    home = work / "home"
    _seed(home, "0.2.14")
    _launch(root, home, models)
    _launch(root, home, models)
    memory = json.loads(next((home / "experts").glob("*/fact_memory.json")).read_text(encoding="utf-8"))
    left = [fact["statement"] for fact in memory["facts"]]
    for text in LEGIT:
        if text not in left:
            sys.exit(f"陈述句被删了: {text}")
    for text in JUNK:
        if text in left:
            sys.exit(f"要求句还在: {text}")
    quarantine = json.loads((home / "cleaned" / "0214-junk.json").read_text(encoding="utf-8"))
    quarantined = [item.get("fact", {}).get("statement") or item.get("text") for item in quarantine["items"]]
    for text in JUNK + ["工匠的名字", "啥名", "那个瑞典来…"]:
        if text not in quarantined:
            sys.exit(f"没有隔离: {text}")
    if "我的职业是翻译" in quarantined:
        sys.exit("职业是翻译被隔离了")
    backups = list(home.glob("memory.bak-*"))
    if len(backups) != 1:
        sys.exit(f"备份不是一份: {backups}")
    marker = json.loads((home / "migrations" / "cleanup-0214.json").read_text(encoding="utf-8"))
    if not marker.get("done"):
        sys.exit("没有迁移标记")
    old = work / "old"
    _seed(old, "0.2.7")
    _launch(root, old, models)
    old_left = [fact["statement"] for fact in json.loads(next((old / "experts").glob("*/fact_memory.json")).read_text(encoding="utf-8"))["facts"]]
    for text in LEGIT:
        if text not in old_left:
            sys.exit(f"0.2.7 的陈述句被动了: {text}")
    print("MIGRATE_0214_OK", len(backups), len(quarantined))


if __name__ == "__main__":
    main()

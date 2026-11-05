"""0.2.14 的目录里有空专家和悬空 id 时，星云接口仍要返回一张图。"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from server_proc import run_until_ready


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    import torch

    models = Path(os.environ.get("LORA_MEMORY_MODELS") or "/tmp/yingyu-models")
    work = Path("/tmp/yingyu-nebula-0214")
    if work.exists():
        import shutil
        shutil.rmtree(work)
    home = work / "home"
    expert = home / "experts" / "expert_1000"
    expert.mkdir(parents=True)
    (expert / "fact_memory.json").write_text(json.dumps({
        "app_version": "0.2.14",
        "entities": ["我"],
        "facts": [
            {"entity": "我", "statement": "我的职业是翻译", "value": "翻译", "app_version": "0.2.14"},
            {"entity": "我", "statement": "帮我翻译这句话", "value": "帮我翻译这句话", "app_version": "0.2.14"},
        ],
    }, ensure_ascii=False), encoding="utf-8")
    torch.save(torch.zeros(1, 8), expert / "router_key.pt")
    empty = home / "experts" / "expert_empty"
    empty.mkdir(parents=True)
    (empty / "fact_memory.json").write_text(json.dumps({"facts": [], "entities": []}), encoding="utf-8")
    torch.save(torch.zeros(1, 8), empty / "router_key.pt")
    rows = [
        {"expert": "expert_1000", "batch": 1000, "n_facts": 2, "key_path": "expert_1000/router_key.pt", "display_name": "我"},
        {"expert": "expert_empty", "batch": 1001, "n_facts": 0, "key_path": "expert_empty/router_key.pt", "display_name": "写一"},
        {"expert": "expert_1001", "batch": 1002, "n_facts": 0, "key_path": "expert_1001/router_key.pt", "display_name": "悬空"},
    ]
    (home / "experts" / "router.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    (home / "app-version.json").write_text(json.dumps({"version": "0.2.14"}), encoding="utf-8")
    env = os.environ.copy()
    env.update({
        "LORA_MEMORY_HOME": str(home),
        "LORA_MEMORY_MODELS": str(models),
        "LORA_MEMORY_DEVICE": "cpu",
        "LORA_MEMORY_PORT": "0",
        "PYTHONPATH": str(root),
        "PYTHONUNBUFFERED": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "LORA_MEMORY_REPO_EXPERTS": "/tmp/yingyu-no-repo-experts",
    })
    proc, port, log = run_until_ready(root, env, 120)
    if not port:
        proc.kill()
        sys.exit(f"服务没有起来\n{log}")
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/nebula", timeout=240) as res:
            body = res.read().decode("utf-8")
            status = res.status
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        proc.kill()
        sys.exit(f"星云接口失败 {exc.code} {body[:500]}")
    finally:
        proc.terminate()
    if status != 200 or "meta" in body.lower() or "expert_1001" in body:
        sys.exit(f"星云不是一张可用的图 {status} {body[:500]}")
    data = json.loads(body)
    experts = data.get("experts") or []
    if not isinstance(experts, list) or not experts:
        sys.exit(f"星云没有专家 {body[:300]}")
    names = [item.get("name") for item in experts]
    if names != ["expert_1000"]:
        sys.exit(f"空专家还在星云上 {names}")
    for fact in data.get("facts") or []:
        attr = str(fact.get("attr") or "")
        value = str(fact.get("value") or "")
        if "章" in attr or "章" in value:
            sys.exit(f"星云仍用章节名 {attr} {value}")
    facts = json.loads((expert / "fact_memory.json").read_text(encoding="utf-8"))["facts"]
    left = [fact["statement"] for fact in facts]
    if "我的职业是翻译" not in left or "帮我翻译这句话" in left:
        sys.exit(f"清理结果不对 {left}")
    print("NEBULA_0214_OK", len(experts))


if __name__ == "__main__":
    main()

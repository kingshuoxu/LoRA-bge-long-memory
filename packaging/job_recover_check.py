"""训练进程已经不在时，取消和继续不能再被「已有训练在进行」挡住。"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from memory_core.service import MemoryService


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="yingyu-job-"))
    home = root / "home"
    job_id = "job_dead"
    job_dir = home / "jobs" / job_id
    job_dir.mkdir(parents=True)
    (job_dir / "status.json").write_text(json.dumps({
        "id": job_id,
        "status": "running",
        "epoch": 7,
        "max_epochs": 12,
        "message": "正在训练第 7 / 12 轮",
        "worker_pid": None,
    }, ensure_ascii=False), encoding="utf-8")
    (home / "jobs" / "current.json").write_text(json.dumps({"id": job_id}), encoding="utf-8")
    expert = home / "experts" / "e1"
    expert.mkdir(parents=True)
    (expert / "fact_memory.json").write_text(json.dumps({
        "facts": [{"entity": "周乔", "statement": "周乔的猫叫米粒。", "value": "米粒"}],
    }, ensure_ascii=False), encoding="utf-8")
    service = MemoryService(home=home, models_dir=root / "models", use_repo_experts=False)
    job = service.current_job()
    if not job or job.get("status") != "failed":
        raise SystemExit(f"中断的训练没有标成可继续：{job}")
    if service.job_running():
        raise SystemExit("进程没了却还算正在训练")
    (job_dir / "status.json").write_text(json.dumps({
        "id": job_id,
        "status": "running",
        "message": "正在训练第 7 / 12 轮",
        "worker_pid": None,
    }, ensure_ascii=False), encoding="utf-8")
    cancelled = service.cancel_job(job_id)
    if cancelled.get("status") != "cancelled" or service.job_running():
        raise SystemExit(f"取消没有放开：{cancelled}")
    spawned: dict[str, str] = {}
    service._spawn = lambda resumed: spawned.setdefault("id", resumed)
    resumed = service.resume_job(job_id)
    if spawned.get("id") != job_id or resumed.get("status") != "running":
        raise SystemExit(f"继续没有开始：{resumed} {spawned}")
    if "米粒" not in (expert / "fact_memory.json").read_text(encoding="utf-8"):
        raise SystemExit("恢复训练时事实被改掉了")
    print("JOB_RECOVER_OK", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"JOB_RECOVER_FAIL {exc}", file=sys.stderr)
        raise

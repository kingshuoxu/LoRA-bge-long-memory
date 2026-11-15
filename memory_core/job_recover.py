"""训练进程没了，就不能再把任务当成还在跑。"""
from __future__ import annotations

import os


def pid_alive(pid: object) -> bool:
    try:
        number = int(pid)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    if number <= 0:
        return False
    try:
        os.kill(number, 0)
    except OSError:
        return False
    return True


def finalize_dead_job(status: dict, *, cancel_requested: bool = False) -> dict:
    """进程不在时结束任务。事实文件不动，只改这一份状态。"""
    current = dict(status)
    if current.get("status") != "running":
        return current
    current["worker_pid"] = None
    if cancel_requested or current.get("cancel_requested"):
        current["status"] = "cancelled"
        current["message"] = "训练已停止"
        current["error"] = None
    else:
        current["status"] = "failed"
        current["message"] = "训练中断了，可以继续"
        current["error"] = "训练进程已经不在"
    return current

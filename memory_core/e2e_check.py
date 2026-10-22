"""端到端验收：写入几条虚构事实，巩固成专家，再在新对话里提问。

退出码 0 表示：事实题全部答对且挂上了新专家，常识题和 CMMLU 风格题没有挂上它。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from memory_core.models_mgr import model_sizes
from memory_core.paths import default_models_dir
from memory_core.service import MemoryService

TURNS = [
    "沈星河的猫的名字是云朵。",
    "沈星河的住址是青岚镇。",
    "沈星河的自行车颜色是朱红色。",
    "沈星河最喜欢的茶是桂花乌龙。",
]

QUESTIONS = [
    ("沈星河的猫的名字是什么？", "云朵"),
    ("请问沈星河的住址是什么？", "青岚镇"),
    ("沈星河的自行车颜色是什么？", "朱红色"),
    ("沈星河最喜欢的茶是什么？", "桂花乌龙"),
]

PARAPHRASE = [
    ("能告诉我沈星河的猫的名字吗？", "云朵"),
    ("沈星河住在哪里？", "青岚镇"),
]

GENERAL = [
    "水的化学式是什么？",
    "法国的首都是哪里？",
    "一年有多少个月？",
    "中国的首都是哪里？",
    "1加1等于几？",
]

CMMLU = [
    "下列哪一项属于中国传统节日？A. 春节 B. 万圣节 C. 感恩节 D. 复活节",
    "光合作用主要发生在植物细胞的哪个结构？A. 线粒体 B. 叶绿体 C. 细胞核 D. 核糖体",
    "《红楼梦》的作者是谁？A. 罗贯中 B. 曹雪芹 C. 吴承恩 D. 施耐庵",
    "下列哪个是质数？A. 4 B. 6 C. 9 D. 7",
    "普通话以哪一种方言为基础方言？A. 吴语 B. 粤语 C. 北方话 D. 闽南语",
]


def _norm(text: str) -> str:
    return text.replace(" ", "").replace("。", "").replace(".", "").replace("\n", "")


def _hit(answer: str, gold: str) -> bool:
    return _norm(gold.rstrip("年")) in _norm(answer)


def _wait(service: MemoryService, job_id: str, timeout: float = 7200) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        status = service.job_status(job_id)
        stamp = (status.get("status"), status.get("epoch"), status.get("message"))
        if stamp != last:
            print(f"[train] {status.get('status')} epoch={status.get('epoch')} {status.get('message')}", flush=True)
            last = stamp
        if status.get("status") in {"done", "failed", "cancelled"}:
            return status
        time.sleep(2)
    raise TimeoutError("训练超时")


def _ask(service: MemoryService, conv_id: str, question: str) -> dict:
    result = service.send_message(conv_id, question)
    route = result["route"]
    answer = result["assistant"]["content"]
    print(f"Q: {question}\nA: {answer}\nroute={route['label']} sim={route['sim']} fired={route['fired']} reason={route['reason']}\n", flush=True)
    return result


def run_check(home: Path, models_dir: Path | None = None, exercise_cancel: bool = False, device: str | None = None) -> dict:
    home = Path(home)
    models = Path(models_dir) if models_dir else default_models_dir()
    service = MemoryService(
        home=home,
        models_dir=models,
        repo_experts=None,
        device=device,
        use_repo_experts=False,
    )
    print(f"home={home}", flush=True)
    print(f"models={models}", flush=True)
    service.ensure_ready()
    sizes = model_sizes(models)
    conv = service.create_conversation()
    base_turns = []
    for turn in TURNS:
        result = _ask(service, conv["id"], turn)
        base_turns.append(result["route"]["fired"])
    preview = service.preview_consolidation([conv["id"]])
    print("extracted:", json.dumps(preview["facts"], ensure_ascii=False, indent=2), flush=True)
    values = {fact["value"] for fact in preview["facts"] if fact.get("selected")}
    missing = [gold for _, gold in QUESTIONS if gold not in values]
    if missing:
        raise RuntimeError(f"抽取没有覆盖这些取值：{missing}")
    selected = [fact for fact in preview["facts"] if fact.get("selected")]
    job = service.start_consolidation([conv["id"]], selected)
    if exercise_cancel:
        deadline = time.time() + 7200
        while time.time() < deadline:
            status = service.job_status(job["id"])
            print(f"[train] {status.get('status')} epoch={status.get('epoch')} {status.get('message')}", flush=True)
            if status.get("status") in {"done", "failed", "cancelled"}:
                break
            if int(status.get("epoch") or 0) >= 1 and status.get("loss") is not None:
                print("request cancel", flush=True)
                service.cancel_job(job["id"])
                status = _wait(service, job["id"])
                if status["status"] != "cancelled":
                    raise RuntimeError(f"取消后状态是 {status['status']}")
                print("resume", flush=True)
                service.resume_job(job["id"])
                break
            time.sleep(2)
    status = _wait(service, job["id"])
    if status.get("status") != "done":
        raise RuntimeError(status.get("error") or status.get("message") or "训练失败")
    expert = status["expert"]
    fresh = service.create_conversation()
    details = []
    hits = 0
    for question, gold in QUESTIONS:
        result = _ask(service, fresh["id"], question)
        route = result["route"]
        answer = result["assistant"]["content"]
        ok = bool(route["fired"] and route["expert"] == expert and _hit(answer, gold))
        hits += int(ok)
        details.append({"q": question, "gold": gold, "answer": answer, "hit": ok, "route": route, "kind": "primary"})
    paraphrase_hits = 0
    paraphrase_details = []
    for question, gold in PARAPHRASE:
        result = _ask(service, fresh["id"], question)
        route = result["route"]
        answer = result["assistant"]["content"]
        ok = bool(route["fired"] and route["expert"] == expert and _hit(answer, gold))
        paraphrase_hits += int(ok)
        paraphrase_details.append({"q": question, "gold": gold, "answer": answer, "hit": ok, "route": route, "kind": "paraphrase"})
    probe = service.create_conversation()
    general_bad = []
    for question in GENERAL:
        result = _ask(service, probe["id"], question)
        route = result["route"]
        if route["fired"] and route["expert"] == expert:
            general_bad.append(question)
    cmmlu_bad = []
    for question in CMMLU:
        result = _ask(service, probe["id"], question)
        route = result["route"]
        if route["fired"] and route["expert"] == expert:
            cmmlu_bad.append(question)
    report = {
        "fact_hits": hits,
        "fact_total": len(QUESTIONS),
        "fact_score": f"{hits}/{len(QUESTIONS)}",
        "paraphrase_hits": paraphrase_hits,
        "paraphrase_total": len(PARAPHRASE),
        "paraphrase_score": f"{paraphrase_hits}/{len(PARAPHRASE)}",
        "details": details,
        "paraphrase_details": paraphrase_details,
        "general_activated_new_expert": len(general_bad),
        "general_total": len(GENERAL),
        "general_failures": general_bad,
        "cmmlu_activated_new_expert": len(cmmlu_bad),
        "cmmlu_total": len(CMMLU),
        "cmmlu_failures": cmmlu_bad,
        "setup_turns_fired": base_turns,
        "expert": expert,
        "train": status,
        "device": service.device_name(),
        "model_bytes": sizes,
        "home": str(home),
    }
    out = home / "e2e-report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("E2E_SCORE", report["fact_score"], flush=True)
    print("E2E_PARAPHRASE", report["paraphrase_score"], flush=True)
    print("E2E_GENERAL_ACTIVATED", f"{report['general_activated_new_expert']}/{report['general_total']}", flush=True)
    print("E2E_CMMLU_ACTIVATED", f"{report['cmmlu_activated_new_expert']}/{report['cmmlu_total']}", flush=True)
    print("E2E_DEVICE", report["device"], "lr", status.get("lr"), "dtype", status.get("dtype"), "best_loss", status.get("best_loss"), flush=True)
    ok = (
        hits == len(QUESTIONS)
        and not general_bad
        and not cmmlu_bad
        and not any(base_turns)
    )
    report["passed"] = ok
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not ok:
        raise RuntimeError("端到端没有通过，详见 e2e-report.json")
    return report


def main():
    parser = argparse.ArgumentParser(description="巩固一段虚构对话并检查新专家")
    parser.add_argument("--home", type=Path, default=None)
    parser.add_argument("--models", type=Path, default=None)
    parser.add_argument("--device", default=None)
    parser.add_argument("--exercise-cancel", action="store_true")
    parser.add_argument("--fresh", action="store_true", default=True)
    parser.add_argument("--no-fresh", action="store_false", dest="fresh")
    args = parser.parse_args()
    if args.home is None:
        if sys.platform == "win32":
            base = Path.home() / "AppData" / "Roaming"
            args.home = base / "lora-bge-memory-e2e"
        elif sys.platform == "darwin":
            args.home = Path.home() / "Library" / "Application Support" / "lora-bge-memory-e2e"
        else:
            args.home = Path.home() / ".local" / "share" / "lora-bge-memory-e2e"
    if args.fresh and args.home.exists():
        import shutil

        shutil.rmtree(args.home)
    try:
        run_check(args.home, args.models, exercise_cancel=args.exercise_cancel, device=args.device)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"E2E_FAIL {exc}", flush=True)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()

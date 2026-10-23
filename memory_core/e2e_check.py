"""端到端验收：写入几条虚构事实，巩固成专家，再在新对话里提问。

退出码 0 表示：事实题全部答对且挂上了新专家；没出现在训练问句里的改写至少 90% 答对；
同一人没写过的属性至少 90% 回基座；常识题和 CMMLU 风格题没有挂上它。
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

# 这些问法不能和 expand_training_fact 展开的训练问句逐字相同。
PARAPHRASE = [
    ("沈星河养的那只猫叫什么名字？", "云朵"),
    ("沈星河家的猫咪叫啥？", "云朵"),
    ("沈星河的宠物猫叫什么？", "云朵"),
    ("沈星河住哪儿？", "青岚镇"),
    ("沈星河的住址在哪儿？", "青岚镇"),
    ("沈星河居住在什么地方？", "青岚镇"),
    ("沈星河那辆自行车是什么颜色？", "朱红色"),
    ("沈星河自行车是什么色的？", "朱红色"),
    ("沈星河最爱喝的茶是哪种？", "桂花乌龙"),
    ("沈星河喜欢喝什么茶？", "桂花乌龙"),
]

# 对话里没写过的属性。挂上新专家就算没弃权。
NEVER = [
    "沈星河的狗叫什么？",
    "沈星河的狗的名字是什么？",
    "沈星河养的狗叫什么名字？",
    "沈星河家的狗叫啥？",
    "沈星河的汽车颜色是什么？",
    "沈星河的车是什么颜色？",
    "沈星河那辆汽车是什么颜色？",
    "沈星河的生日是什么时候？",
    "沈星河哪天生日？",
    "沈星河会弹古筝吗？",
    "沈星河的电话是多少？",
    "沈星河的母亲是谁？",
    "沈星河多大了？",
    "沈星河的学校叫什么？",
    "沈星河喜欢吃什么？",
]

# 研究仓库里的常识题是 data/generic_questions.jsonl 的 20 条，再加上
# scripts/eval_entity_guard_realistic.py 的 15 条。没有单独的 40 题文件，
# 三个研究路由键仍是 Git LFS 指针，全量研究专家跑不起来。这里把这两份并成
# 桌面验收的常识集，新专家挂上任意一条都算误激活。
GENERAL = [
    "水的化学式是什么？",
    "一年有多少个月？",
    "法国的首都是哪里？",
    "地球绕太阳公转一周大约多久？",
    "1加1等于几？",
    "光合作用发生在植物的哪个器官？",
    "英语中苹果怎么拼？",
    "一周有几天？",
    "冰在标准大气压下多少度融化？",
    "中国的首都是哪里？",
    "三角形内角和是多少度？",
    "月亮是行星还是卫星？",
    "人体最大的器官是什么？",
    "光速大约是多少？",
    "莎士比亚是哪国人？",
    "计算机的CPU全称是什么？",
    "氧气在空气中大约占多少比例？",
    "太阳系最大的行星是哪颗？",
    "水沸腾的温度是多少摄氏度？",
    "中国的官方语言是什么？",
    "今天天气怎么样？",
    "红烧肉怎么做比较入味？",
    "世界杯几年举办一次？",
    "Python是什么编程语言？",
    "长江的长度大约是多少公里？",
    "《红楼梦》的作者是谁？",
    "月球离地球有多远？",
    "如何煮一碗清汤面条？",
    "银行定期存款利率是什么意思？",
    "光合作用的主要产物是什么？",
    "为什么海水是咸的？",
    "钢琴有多少个键？",
    "奥运会首次举办是在哪一年？",
    "蓝牙技术是用来做什么的？",
    "赤道附近的气候有什么特点？",
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
    abstain_hits = 0
    abstain_details = []
    for question in NEVER:
        result = _ask(service, fresh["id"], question)
        route = result["route"]
        answer = result["assistant"]["content"]
        ok = not (route["fired"] and route["expert"] == expert)
        abstain_hits += int(ok)
        abstain_details.append({"q": question, "answer": answer, "abstain": ok, "route": route, "kind": "never"})
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
        "abstain_hits": abstain_hits,
        "abstain_total": len(NEVER),
        "abstain_score": f"{abstain_hits}/{len(NEVER)}",
        "details": details,
        "paraphrase_details": paraphrase_details,
        "abstain_details": abstain_details,
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
    print("E2E_ABSTAIN", report["abstain_score"], flush=True)
    print("E2E_GENERAL_ACTIVATED", f"{report['general_activated_new_expert']}/{report['general_total']}", flush=True)
    print("E2E_CMMLU_ACTIVATED", f"{report['cmmlu_activated_new_expert']}/{report['cmmlu_total']}", flush=True)
    print("E2E_DEVICE", report["device"], "lr", status.get("lr"), "dtype", status.get("dtype"), "best_loss", status.get("best_loss"), flush=True)
    paraphrase_rate = paraphrase_hits / len(PARAPHRASE) if PARAPHRASE else 1.0
    abstain_rate = abstain_hits / len(NEVER) if NEVER else 1.0
    base_ok = (
        hits == len(QUESTIONS)
        and paraphrase_rate >= 0.90
        and abstain_rate >= 0.90
        and not general_bad
        and not cmmlu_bad
        and not any(base_turns)
    )
    correction = {"ok": False}
    if base_ok:
        utterance = "沈星河的猫的名字不是云朵，正确的是暮雪。"
        proposal = service.propose_correction(utterance)
        print("correction proposal:", json.dumps(proposal, ensure_ascii=False), flush=True)
        if not proposal or proposal.get("new_value") != "暮雪" or proposal.get("old_value") != "云朵":
            raise RuntimeError(f"没有对上猫的名字这条纠正：{proposal}")
        question_like = service.propose_correction("沈星河的猫的名字是什么？")
        if question_like is not None:
            raise RuntimeError(f"普通提问被当成了纠正：{question_like}")
        corr_job = service.commit_correction(proposal)
        corr_status = _wait(service, corr_job["id"])
        if corr_status.get("status") != "done":
            raise RuntimeError(corr_status.get("error") or corr_status.get("message") or "纠正训练失败")
        if corr_status.get("expert") != expert:
            raise RuntimeError(f"纠正换了专家名：{corr_status.get('expert')} != {expert}")
        corrected = service.create_conversation()
        cat = _ask(service, corrected["id"], "沈星河的猫的名字是什么？")
        cat_answer = cat["assistant"]["content"]
        cat_route = cat["route"]
        cat_ok = bool(
            cat_route["fired"]
            and cat_route["expert"] == expert
            and _hit(cat_answer, "暮雪")
            and "云朵" not in _norm(cat_answer)
        )
        addr = _ask(service, corrected["id"], "请问沈星河的住址是什么？")
        addr_answer = addr["assistant"]["content"]
        addr_ok = bool(addr["route"]["fired"] and addr["route"]["expert"] == expert and _hit(addr_answer, "青岚镇"))
        cloud = service.nebula()
        dim = [fact for fact in cloud["facts"] if fact.get("superseded") and fact.get("value") == "云朵"]
        bright = [fact for fact in cloud["facts"] if not fact.get("superseded") and fact.get("value") == "暮雪"]
        nebula_ok = bool(dim and bright)
        correction = {
            "ok": bool(cat_ok and addr_ok and nebula_ok),
            "cat_answer": cat_answer,
            "cat_ok": cat_ok,
            "address_answer": addr_answer,
            "address_ok": addr_ok,
            "nebula_ok": nebula_ok,
            "expert": corr_status.get("expert"),
            "train": corr_status,
        }
        print("E2E_CORRECTION", "1/1" if correction["ok"] else "0/1", flush=True)
        print("E2E_CORRECTION_CAT", cat_answer, flush=True)
        print("E2E_CORRECTION_ADDR", addr_answer, flush=True)
    report["correction"] = correction
    ok = base_ok and bool(correction.get("ok"))
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

"""真实模型下的文档问答、弃权和身份迁移。不打开 LORA_MEMORY_E2E_FAST。"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from pathlib import Path

from memory_core.documents import covered_fact, extract_key_points, fact_from_point, split_chapters
from memory_core.identity import migrate_user_identity
from memory_core.self_query import self_reply
from memory_core.service import MemoryService


def _fail(message: str) -> None:
    raise SystemExit(message)


def _identity(root: Path) -> None:
    home = root / "identity"
    expert = home / "experts" / "expert_1000"
    expert.mkdir(parents=True)
    (expert / "fact_memory.json").write_text(json.dumps({
        "expert": "expert_1000",
        "display_name": "用户/徐金朔",
        "entities": ["用户"],
        "facts": [{
            "entity": "用户",
            "attr": "名字",
            "value": "徐金朔",
            "statement": "用户叫徐金朔。",
        }],
    }, ensure_ascii=False), encoding="utf-8")
    if migrate_user_identity(home) < 1:
        _fail("身份迁移没有改写用户")

    class Expert:
        name = "expert_1000"
        display_name = "关于你"
        fact_memory = json.loads((expert / "fact_memory.json").read_text(encoding="utf-8"))

    for question in ("我是谁？", "我叫什么名字？", "我的名字是什么？"):
        answer, owner, used = self_reply(question, [Expert()])
        if "徐金朔" not in answer or owner is None or not used:
            _fail(f"{question} -> {answer}")
    again = {
        "entity": "我",
        "attr": "名字",
        "value": "徐金朔",
        "statement": "我叫徐金朔。",
    }
    from memory_core.same_memory import is_same_memory

    stored = Expert.fact_memory["facts"][0]["statement"]
    if not is_same_memory(again["statement"], stored):
        _fail(f"再说一遍对不上旧事实: {stored}")
    print("FULL_IDENTITY_OK", flush=True)


def _wait_doc(service: MemoryService, timeout: float = 900) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        status = service.document_status()
        phase = status.get("phase")
        if phase != last:
            print(f"[doc] {phase} {status.get('percent')} {status.get('message') or status.get('title') or ''}", flush=True)
            last = phase
        if phase in {"done", "error"}:
            return status
        time.sleep(2)
    _fail("文档导入超时")
    return {}


def _ask(service: MemoryService, conv_id: str, question: str) -> str:
    result = service.send_message(conv_id, question)
    answer = result["assistant"]["content"]
    print(f"Q: {question}\nA: {answer}\n", flush=True)
    return answer


def _book(service: MemoryService, book: Path) -> None:
    if os.environ.get("LORA_MEMORY_E2E_FAST") == "1":
        _fail("全量检查不能开 fast 模式")
    service.start_document_import(str(book))
    status = _wait_doc(service)
    if status.get("phase") != "done":
        _fail(f"导入失败: {status}")
    docs = service.list_documents()
    if not docs:
        _fail("没有索引")
    points = docs[0].get("points") or []
    blob = "\n".join(str(point.get("text") or "") for point in points)
    if any(ch in blob for ch in "⻚⻩⺠⻛⻥⻘"):
        _fail("重点里还有部首字")
    if "1873" not in blob or "霜降" not in blob:
        _fail(f"重点漏了年份或霜降: {blob[:400]}")
    conv = service.create_conversation("文档")["id"]
    year = _ask(service, conv, "白鹭塔建于哪一年？")
    if "1873" not in year or "1987" in year:
        _fail(f"年份不可靠: {year}")
    if "白鹭塔" not in year and "建于" not in year:
        _fail(f"年份没有引用原文: {year}")
    height = _ask(service, conv, "白鹭塔有多高？")
    if "四十二米" not in height:
        _fail(f"高度不可靠: {height}")
    mayor = _ask(service, conv, "雾港的市长是谁？")
    if "没有找到" not in mayor:
        _fail(f"市长不该编造: {mayor}")
    gull = _ask(service, conv, "柯小满的海鸥叫什么？")
    if "阿哨" not in gull or "小燕子" in gull:
        _fail(f"海鸥不可靠: {gull}")
    print("FULL_DOCUMENT_OK", flush=True)


def _abstain(service: MemoryService) -> None:
    conv = service.create_conversation("弃权")["id"]
    dog = _ask(service, conv, "我的狗叫什么名字？")
    if "旺财" in dog or "不在记忆里" not in dog:
        _fail(f"狗不该编造: {dog}")
    color = _ask(service, conv, "我最喜欢的颜色是什么？")
    if "蓝色" in color or "不在记忆里" not in color:
        _fail(f"颜色不该编造: {color}")
    print("FULL_ABSTAIN_OK", flush=True)


def _recall_without_subject() -> None:
    line = "柯岚的女儿柯小满养了一只三条腿的海鸥，名叫阿哨。"
    fact = fact_from_point(line, "雾港灯塔志", "第三章 守塔人的女儿")
    if fact["entity"] != "柯小满" or fact["value"] != "阿哨":
        _fail(f"海鸥事实的主体不对: {fact['entity']} {fact['value']}")
    legacy = dict(fact)
    legacy["entity"] = "阿哨"
    legacy["statement"] = line if line.endswith("。") else line + "。"
    hit = covered_fact("柯小满的海鸥叫什么", [legacy])
    if hit is None or "阿哨" not in str(hit.get("statement")):
        _fail("删书后不带专家名召不回阿哨")
    print("FULL_RECALL_OK", flush=True)


def _wait_job(service: MemoryService, job_id: str, timeout: float = 1800) -> dict:
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
    _fail("训练超时")
    return {}


def _declined(answer: str) -> bool:
    text = answer or ""
    if any(mark in text for mark in ("不在记忆里", "还不知道", "没有找到")):
        return True
    return False


def _learning(service: MemoryService) -> None:
    """删掉文档之后，用真实训练过的事实回答学习效果表。"""
    if os.environ.get("LORA_MEMORY_E2E_FAST") == "1":
        _fail("学习效果检查不能开 fast 模式")
    named = service.create_conversation("名字")["id"]
    service.send_message(named, "我叫徐金朔")
    for doc in service.list_documents():
        ids = [str(point.get("id") or "") for point in doc.get("points") or [] if point.get("id")]
        if ids:
            service.queue_document_points(doc["id"], ids)
    pending = service.list_pending()
    if len(pending) < 4:
        _fail(f"待巩固不足 4 条: {len(pending)}")
    job = service.train_pending()
    status = _wait_job(service, job["id"])
    if status.get("status") != "done":
        _fail(f"训练没有完成: {status.get('status')} {status.get('error') or status.get('message')}")
    for doc in list(service.list_documents()):
        service.remove_document(doc["id"])
    if service.list_documents():
        _fail("文档没有删干净")
    taught = [
        ("白鹭塔建于哪一年？", "1873"),
        ("柯小满的海鸥叫什么？", "阿哨"),
        ("星砂盐什么时候开始晾晒？", "霜降"),
        ("白鹭塔有多高？", "四十二"),
        ("那只三条腿的海鸥叫什么名字？", "阿哨"),
        ("柯岚守护的第一座灯塔是哪年建的？", "1873"),
        ("雾港的蓝色海盐每年哪天开始晒？", "霜降"),
        ("雾港的特产是什么？", "星砂盐"),
        ("白鹭塔哪一年改用电灯？", "1931"),
        ("白鹭塔的透镜是谁打磨的？", "诺丁"),
        ("透镜一共有多少面？", "十六"),
    ]
    never = [
        "雾港的市长是谁？",
        "柯岚的妻子叫什么名字？",
        "白鹭塔的灯光能照多远？",
        "柯小满今年几岁？",
    ]
    pets = ["我的狗叫什么名字？", "我的猫叫什么名字？"]
    taught_hits = 0
    for question, gold in taught:
        conv = service.create_conversation("学习")["id"]
        answer = _ask(service, conv, question)
        if gold in answer:
            taught_hits += 1
        else:
            print(f"MISS {question} -> {answer}", flush=True)
    declined = 0
    for question in never:
        conv = service.create_conversation("弃权")["id"]
        answer = _ask(service, conv, question)
        bad = any(mark in answer for mark in ("陈国强", "李世民", "三脚"))
        if _declined(answer) and not bad:
            declined += 1
        else:
            print(f"ABSTAIN_MISS {question} -> {answer}", flush=True)
    for question in pets:
        conv = service.create_conversation("宠物")["id"]
        answer = _ask(service, conv, question)
        if "徐金朔" in answer or not _declined(answer):
            _fail(f"宠物名字不该答成用户：{question} -> {answer}")
    print(f"LEARNING taught {taught_hits}/{len(taught)} declined {declined}/{len(never)}", flush=True)
    if taught_hits < 10:
        _fail(f"教过的事实只答对 {taught_hits}/11")
    if declined < 4:
        _fail(f"没教过的问题只弃权 {declined}/4")
    print("FULL_LEARNING_OK", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", type=Path, default=None)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--book", type=Path, required=True)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()
    if not args.book.is_file():
        _fail(f"找不到 {args.book}")
    home = args.home or Path(tempfile.mkdtemp(prefix="yingyu-full-"))
    home.mkdir(parents=True, exist_ok=True)
    _identity(home)
    _recall_without_subject()
    chapters = split_chapters("第一章 白鹭塔\n柯岚在雾港守护的第一座灯塔名叫白鹭塔，建于1873年，塔高四十二米。")
    points = extract_key_points(chapters, ask=lambda _prompt: "镇上的人习惯在黄昏时分聚到石阶上。")
    if not any("1873" in point["text"] for point in points):
        _fail("景物句盖过了年份")
    service = MemoryService(
        home=home / "chat",
        models_dir=args.models,
        repo_experts=None,
        device=args.device,
        use_repo_experts=False,
    )
    service.ensure_ready()
    _abstain(service)
    _book(service, args.book)
    _learning(service)
    print("FULL_MODE_OK", flush=True)


if __name__ == "__main__":
    main()

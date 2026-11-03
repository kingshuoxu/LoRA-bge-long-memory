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
    print("FULL_MODE_OK", flush=True)


if __name__ == "__main__":
    main()

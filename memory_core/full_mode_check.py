"""真实模型下的文档问答、弃权和身份迁移。不打开 LORA_MEMORY_E2E_FAST。"""
from __future__ import annotations

import argparse
import json
import os
import re
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
    if "旺财" in dog or not any(mark in dog for mark in ("不在记忆里", "还没告诉过我")):
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
    if any(mark in text for mark in ("不在记忆里", "还不知道", "没有找到", "没有存过", "还没告诉过我", "没提到", "不记得", "还没告诉", "没记过", "我不确定")):
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
    _generated(service, 20261212, "抽查")
    _open_chat(service)
    _generated(service, 20261213, "盲测")
    _known_fence(service)
    _spouse_and_kin(service)
    _new_traps(service)
    _role_sets(service)
    print("FULL_LEARNING_OK", flush=True)


def _new_traps(service: MemoryService) -> None:
    """是A还是B不能把其中一边说成已经记住。俗称配偶、看守人、谁磨的各有一套。"""
    from memory_core.blind_heldout import _EITHER, _KEEPER_CALLED, _SPOKEN_SPOUSE, _WHO_MADE
    from memory_core.extract import is_question_fragment

    either_bad = 0
    for question in _EITHER:
        conv = service.create_conversation("两选")["id"]
        answer = _ask(service, conv, question)
        asserted = bool(re.search(r"我记得[^，]{0,12}是", answer))
        if not _declined(answer) or asserted:
            either_bad += 1
            print(f"EITHER {question} -> {answer}", flush=True)
    spoken_bad = 0
    for question in _SPOKEN_SPOUSE:
        conv = service.create_conversation("俗称")["id"]
        answer = _ask(service, conv, question)
        if not _declined(answer) or answer.strip().rstrip("。") in {"白鹭塔", "雾港", "阿哨"}:
            spoken_bad += 1
            print(f"SPOKEN {question} -> {answer}", flush=True)
    keeper_hits = 0
    for question, gold in _KEEPER_CALLED:
        conv = service.create_conversation("看守")["id"]
        answer = _ask(service, conv, question)
        if gold in answer and "白鹭塔" not in answer:
            keeper_hits += 1
        else:
            print(f"KEEPER {question} -> {answer}", flush=True)
    made_hits = 0
    for question, gold in _WHO_MADE:
        conv = service.create_conversation("打磨")["id"]
        answer = _ask(service, conv, question)
        if gold in answer and "柯岚" not in answer:
            made_hits += 1
        else:
            print(f"MADE {question} -> {answer}", flush=True)
    leaked = []
    for record in service.expert_records():
        for fact in (getattr(record, "fact_memory", None) or {}).get("facts") or []:
            statement = str(fact.get("statement") or "")
            if is_question_fragment(statement):
                leaked.append(statement)
    for item in service.list_pending():
        statement = str(item.get("statement") or "")
        if is_question_fragment(statement):
            leaked.append(statement)
    print(
        f"EITHER {len(_EITHER) - either_bad}/{len(_EITHER)} bad {either_bad} "
        f"SPOKEN {len(_SPOKEN_SPOUSE) - spoken_bad}/{len(_SPOKEN_SPOUSE)} bad {spoken_bad} "
        f"KEEPER {keeper_hits}/{len(_KEEPER_CALLED)} MADE {made_hits}/{len(_WHO_MADE)} "
        f"QUESTION_FACTS {len(leaked)}",
        flush=True,
    )
    if either_bad:
        _fail(f"是A还是B把一边说成了事实 {either_bad} 次")
    if spoken_bad:
        _fail(f"俗称配偶答成了塔或别的东西 {spoken_bad} 次")
    if keeper_hits < len(_KEEPER_CALLED):
        _fail(f"看守人叫什么只答对 {keeper_hits}/{len(_KEEPER_CALLED)}")
    if made_hits < len(_WHO_MADE):
        _fail(f"谁磨的只答对 {made_hits}/{len(_WHO_MADE)}")
    if leaked:
        _fail(f"问句被存成了事实：{leaked[:3]}")
    pending_bad = [
        str(item.get("statement") or "")
        for item in service.list_pending()
        if is_question_fragment(str(item.get("statement") or "")) or "还是" in str(item.get("statement") or "")
    ]
    print(f"PENDING_QUESTIONS {len(pending_bad)}", flush=True)
    if pending_bad:
        _fail(f"待巩固里还有问句：{pending_bad[:3]}")


def _role_sets(service: MemoryService) -> None:
    """闺女要答到孩子，盐的地方的灯塔要答塔，守塔不能答成磨透镜的人。"""
    from memory_core.blind_heldout import _DAUGHTER_CHAINS, _GUARD_NOT_MAKE, _SALT_TOWERS

    def ask(label, pairs, gold_ok, bad_name):
        hits = 0
        for question, gold in pairs:
            conv = service.create_conversation(label)["id"]
            answer = _ask(service, conv, question)
            if gold in answer and bad_name not in answer:
                hits += 1
            else:
                print(f"{label} {question} -> {answer}", flush=True)
        return hits

    from memory_core.blind_heldout import (
        diverse_guards,
        diverse_towers,
        duty_watchers,
        named_towers,
        omitted_tower_guards,
        question_prefixes,
        relative_makers,
        gull_father_towers,
        gull_owner_makers,
    )
    from memory_core.extract import pattern_extract

    daughter = ask("DAUGHTER", _DAUGHTER_CHAINS, "柯小满", "柯岚")
    towers = ask("SALT_TOWER", _SALT_TOWERS, "白鹭塔", "星砂盐")
    guards = ask("GUARD", _GUARD_NOT_MAKE, "柯岚", "诺丁")
    fresh_guards = diverse_guards()
    fresh_towers = diverse_towers()
    duties = duty_watchers()
    guard_hits = 0
    type_ok = 0
    for question in fresh_guards:
        conv = service.create_conversation("守塔")["id"]
        answer = _ask(service, conv, question)
        if "柯岚" in answer and "诺丁" not in answer:
            guard_hits += 1
            if not any(mark in answer for mark in ("1931", "1873", "雾港", "白鹭塔", "四十二", "星砂盐")):
                type_ok += 1
        else:
            print(f"FRESH_GUARD {question} -> {answer}", flush=True)
    tower_hits = 0
    for question in fresh_towers:
        conv = service.create_conversation("早塔")["id"]
        answer = _ask(service, conv, question)
        if "白鹭塔" in answer and "星砂盐" not in answer and not answer.startswith("雾港"):
            tower_hits += 1
        else:
            print(f"FRESH_TOWER {question} -> {answer}", flush=True)
    duty_hits = 0
    for question in duties:
        conv = service.create_conversation("尽责")["id"]
        answer = _ask(service, conv, question)
        if "柯岚" in answer and "诺丁" not in answer and not any(mark in answer for mark in ("没提到", "不确定", "不在记忆")):
            duty_hits += 1
        else:
            print(f"DUTY {question} -> {answer}", flush=True)
    name_hits = 0
    for question in named_towers():
        conv = service.create_conversation("塔名")["id"]
        answer = _ask(service, conv, question)
        head = answer.splitlines()[0] if answer else ""
        if "白鹭塔" in head and "柯岚" not in head and "星砂盐" not in head:
            name_hits += 1
        else:
            print(f"TOWER_NAME {question} -> {answer}", flush=True)
    omit_hits = 0
    for question in omitted_tower_guards():
        conv = service.create_conversation("不提塔")["id"]
        answer = _ask(service, conv, question)
        if "柯岚" in answer and "诺丁" not in answer and "打磨" not in answer and "1931" not in answer:
            omit_hits += 1
        else:
            print(f"OMIT_GUARD {question} -> {answer}", flush=True)
    made_hits = 0
    for question, _gold in relative_makers():
        conv = service.create_conversation("磨的")["id"]
        answer = _ask(service, conv, question)
        head = answer.splitlines()[0] if answer else ""
        if "诺丁" in head and "柯岚" not in head:
            made_hits += 1
        else:
            print(f"REL_MADE {question} -> {answer}", flush=True)
    prefix_kept = [item for item in question_prefixes() if pattern_extract(item)]
    gull_hits = 0
    for question in gull_father_towers():
        conv = service.create_conversation("海鸥姑娘")["id"]
        answer = _ask(service, conv, question)
        head = answer.splitlines()[0] if answer else ""
        if "白鹭塔" in head and "柯岚" not in head and "柯小满" not in head:
            gull_hits += 1
        else:
            print(f"GULL_TOWER {question} -> {answer}", flush=True)
    owner_hits = 0
    for question, _gold in gull_owner_makers():
        conv = service.create_conversation("海鸥师傅")["id"]
        answer = _ask(service, conv, question)
        head = answer.splitlines()[0] if answer else ""
        if "诺丁" in head and "柯岚" not in head:
            owner_hits += 1
        else:
            print(f"GULL_MADE {question} -> {answer}", flush=True)
    print(
        f"DAUGHTER {daughter}/{len(_DAUGHTER_CHAINS)} "
        f"SALT_TOWER {towers}/{len(_SALT_TOWERS)} "
        f"GUARD {guards}/{len(_GUARD_NOT_MAKE)} "
        f"FRESH_GUARD {guard_hits}/{len(fresh_guards)} type {type_ok} "
        f"FRESH_TOWER {tower_hits}/{len(fresh_towers)} "
        f"DUTY {duty_hits}/{len(duties)} "
        f"TOWER_NAME {name_hits}/{len(named_towers())} "
        f"OMIT_GUARD {omit_hits}/{len(omitted_tower_guards())} "
        f"REL_MADE {made_hits}/{len(relative_makers())} "
        f"PREFIX {len(prefix_kept)} "
        f"GULL_TOWER {gull_hits}/{len(gull_father_towers())} "
        f"GULL_MADE {owner_hits}/{len(gull_owner_makers())}",
        flush=True,
    )
    if daughter < len(_DAUGHTER_CHAINS):
        _fail(f"闺女链只答对 {daughter}/{len(_DAUGHTER_CHAINS)}")
    if towers < len(_SALT_TOWERS):
        _fail(f"盐的地方的灯塔只答对 {towers}/{len(_SALT_TOWERS)}")
    if guards < len(_GUARD_NOT_MAKE):
        _fail(f"守塔和打磨只答对 {guards}/{len(_GUARD_NOT_MAKE)}")
    if len(fresh_guards) < 12 or guard_hits < len(fresh_guards) or type_ok < 8:
        _fail(f"换说法的守塔题 {guard_hits}/{len(fresh_guards)}，类型对的 {type_ok}")
    if len(fresh_towers) < 8 or tower_hits < len(fresh_towers):
        _fail(f"换说法的早塔题 {tower_hits}/{len(fresh_towers)}")
    if len(duties) < 12 or duty_hits < len(duties):
        _fail(f"换说法的尽责守塔 {duty_hits}/{len(duties)}")
    if len(named_towers()) < 12 or name_hits < len(named_towers()):
        _fail(f"灯塔叫什么答成了人 {name_hits}/{len(named_towers())}")
    if len(omitted_tower_guards()) < 12 or omit_hits < len(omitted_tower_guards()):
        _fail(f"后半句没提塔的守塔题 {omit_hits}/{len(omitted_tower_guards())}")
    if len(relative_makers()) < 6 or made_hits < len(relative_makers()):
        _fail(f"定语里看守、问的是谁磨 {made_hits}/{len(relative_makers())}")
    if prefix_kept:
        _fail(f"问句的前半句被当成事实：{prefix_kept[:2]}")
    if len(gull_father_towers()) < 12 or gull_hits < len(gull_father_towers()):
        _fail(f"三条腿海鸥姑娘她爸爸的灯塔 {gull_hits}/{len(gull_father_towers())}")
    if len(gull_owner_makers()) < 12 or owner_hits < len(gull_owner_makers()):
        _fail(f"海鸥主人她爸爸看守、问师傅 {owner_hits}/{len(gull_owner_makers())}")


def _spouse_and_kin(service: MemoryService) -> None:
    """没教过的配偶只能是固定句式。鸟的主人她爹要答到父亲，不能答宠物。"""
    from memory_core.blind_heldout import _KIN_NESTED, _SPOUSE_TRAPS

    spouse_bad = 0
    for question in _SPOUSE_TRAPS:
        conv = service.create_conversation("配偶")["id"]
        answer = _ask(service, conv, question)
        borrowed = any(word in answer and word not in question for word in ("阿哨", "四十二", "1873", "1931", "诺丁", "星砂盐"))
        if not _declined(answer) or borrowed or answer.strip().rstrip("。") in {"白鹭塔", "雾港", "阿哨"}:
            spouse_bad += 1
            print(f"SPOUSE {question} -> {answer}", flush=True)
    kin_hits = 0
    for question, gold in _KIN_NESTED:
        conv = service.create_conversation("亲属")["id"]
        answer = _ask(service, conv, question)
        if gold in answer and "阿哨" not in answer:
            kin_hits += 1
        else:
            print(f"KIN {question} -> {answer}", flush=True)
    print(
        f"SPOUSE {len(_SPOUSE_TRAPS) - spouse_bad}/{len(_SPOUSE_TRAPS)} bad {spouse_bad} "
        f"KIN {kin_hits}/{len(_KIN_NESTED)}",
        flush=True,
    )
    if spouse_bad:
        _fail(f"配偶问题答成了同一句里的别的东西 {spouse_bad} 次")
    if kin_hits < len(_KIN_NESTED):
        _fail(f"嵌套亲属只答对 {kin_hits}/{len(_KIN_NESTED)}")


def _known_fence(service: MemoryService) -> None:
    """记住了的人没有这条属性时，只能是固定句式，不能让基座编名字或数字。"""
    from memory_core.blind_heldout import _DENY, _FENCE

    if len(_FENCE) < 15:
        _fail("已知实体的未知属性不足 15 条")
    invented = 0
    for question in _FENCE:
        conv = service.create_conversation("围栏")["id"]
        answer = _ask(service, conv, question)
        leaked = [word for word in _DENY if word in answer]
        if not _declined(answer) or leaked:
            invented += 1
            print(f"FENCE {question} -> {answer}", flush=True)
    print(f"FENCE {len(_FENCE) - invented}/{len(_FENCE)} invented {invented}", flush=True)
    if invented:
        _fail(f"已知实体的未知属性被编造了 {invented} 次")


_STORED_VALUES = (
    "1873", "1931", "四十二", "十六", "阿哨", "柯小满", "柯岚", "白鹭塔",
    "星砂盐", "诺丁", "瑞典", "霜降", "雾港", "徐金朔", "福州", "福建",
)


def _hard_fail(answer: str, gold: str | None, abstain: bool) -> bool:
    """答错还带着取值，或该弃权却给了答案。漏答不算。"""
    text = answer or ""
    if abstain:
        return not _declined(text)
    if _declined(text) or not gold:
        return False
    if re.search(r"年[\u4e00-\u9fff]", text):
        return True
    if gold not in text:
        for value in _STORED_VALUES:
            if value in text and value not in gold and gold not in value:
                return True
        return False
    for value in _STORED_VALUES:
        if value in text and value not in gold and gold not in value:
            return True
    return False


_OPEN_CHAT = (
    "帮我写一句生日祝福",
    "帮我写一句给朋友的生日祝福",
    "帮我写一句新年祝福",
    "帮我写一封简短的感谢信",
    "写一首关于秋天的四行小诗",
    "写一首关于大海的短诗",
    "给我说个笑话",
    "给我讲个笑话",
    "给点学习建议",
    "我最近总失眠，有什么办法？",
    "我有点累，有什么建议？",
    "把「早上好」翻译成英文",
    "把这句话翻译成英文：今天天气不错",
    "帮我把这句话润色一下：今天来晚了",
    "你好",
    "今天心情不太好，随便聊聊",
    "水的化学式是什么？",
    "法国的首都是哪里？",
    "1加1等于几？",
    "英语里谢谢怎么说？",
    "推荐一本适合睡前看的书",
    "怎么煮一碗清汤面？",
    "中国的首都是哪里？",
    "解释一下什么是隐喻",
    "列三个周末可以做的小事",
    "请推荐一部轻松的电影",
    "帮我回复朋友：今晚有空",
)


def _open_chat(service: MemoryService) -> None:
    """写、译、聊、建议必须走基座，而且不能被存成事实。"""
    from memory_core.extract import is_advice_question, is_imperative_request, pattern_extract

    gated = {"memory_miss", "entity_clarify", "entity_grounded", "personal_unknown", "document_miss", "self_empty", "statement_ack", "already"}
    refused = ("不在记忆里", "没提到", "没记过", "还没告诉过我", "不记得", "我不确定", "边界守卫没有通过")
    if len(_OPEN_CHAT) < 25:
        _fail("日常对话回归题太少")
    for prompt in _OPEN_CHAT:
        if is_imperative_request(prompt) or is_advice_question(prompt):
            if pattern_extract(prompt):
                _fail(f"要求句被抽成了事实：{prompt} -> {pattern_extract(prompt)}")
        before = [item.get("statement") for item in service.list_pending()]
        conv = service.create_conversation("日常")["id"]
        result = service.send_message(conv, prompt)
        answer = result["assistant"]["content"]
        reason = str(result["route"].get("reason") or "")
        if reason in gated or result["route"].get("fired") or any(mark in answer for mark in refused):
            _fail(f"日常对话被记忆拦住了：{prompt} -> {answer} reason={reason} fired={result['route'].get('fired')}")
        after = [item.get("statement") for item in service.list_pending()]
        if any(item not in before for item in after):
            _fail(f"日常对话被写进了待巩固：{prompt} -> {after}")
    print(f"OPEN_CHAT {len(_OPEN_CHAT)}/{len(_OPEN_CHAT)}", flush=True)


def _generated(service: MemoryService, seed: int, label: str) -> None:
    """当场用种子抽题，不读仓库里的固定题面。"""
    from memory_core.blind_heldout import generate

    data = generate(seed)
    taught = [(item["q"], item["gold"], int(item.get("hops") or 1)) for item in data["taught"]]
    never = list(data["never"])
    single = [(question, gold) for question, gold, hops in taught if hops < 2]
    multi = [(question, gold) for question, gold, hops in taught if hops >= 2]
    if len(single) < 15 or len(multi) < 8 or len(never) < 15:
        _fail("盲测题太少")
    hard = 0
    single_hits = 0
    multi_hits = 0
    for question, gold in single:
        conv = service.create_conversation("盲测")["id"]
        answer = _ask(service, conv, question)
        if _hard_fail(answer, gold, False):
            hard += 1
            print(f"HARD {question} -> {answer}", flush=True)
        elif gold in answer and len(answer) <= 16:
            single_hits += 1
        else:
            print(f"BLIND_MISS {question} -> {answer}", flush=True)
    for question, gold in multi:
        conv = service.create_conversation("盲测")["id"]
        answer = _ask(service, conv, question)
        if _hard_fail(answer, gold, False):
            hard += 1
            print(f"HARD {question} -> {answer}", flush=True)
        elif gold in answer and len(answer) <= 16:
            multi_hits += 1
        else:
            print(f"BLIND_MISS {question} -> {answer}", flush=True)
    for question in never:
        conv = service.create_conversation("盲测弃权")["id"]
        answer = _ask(service, conv, question)
        if _hard_fail(answer, None, True):
            hard += 1
            print(f"HARD_ABSTAIN {question} -> {answer}", flush=True)
    single_rate = 100 * single_hits // len(single)
    multi_rate = 100 * multi_hits // len(multi)
    print(
        f"{label} single {single_hits}/{len(single)}={single_rate}% chain {multi_hits}/{len(multi)}={multi_rate}% hard {hard} seed {seed}",
        flush=True,
    )
    if hard:
        _fail(f"{label}出现 {hard} 次硬错误")
    if single_hits * 100 < 90 * len(single):
        _fail(f"{label}单跳只答对 {single_hits}/{len(single)}")
    if multi_hits * 100 < 70 * len(multi):
        _fail(f"{label}两跳只答对 {multi_hits}/{len(multi)}")


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

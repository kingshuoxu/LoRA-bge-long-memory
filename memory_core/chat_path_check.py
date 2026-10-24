"""按用户的路径验收：自由对话、抽取、预览、巩固，再在新对话里提问。

人设由 unseen_personas 用固定种子生成，不拿去改阈值。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from memory_core.e2e_check import _wait
from memory_core.service import MemoryService
from memory_core.unseen_personas import build


def _norm(text: str) -> str:
    return "".join(str(text or "").casefold().split())


def _covered(value: str, facts: list[dict]) -> bool:
    needle = _norm(value)
    for fact in facts:
        if not fact.get("selected", True):
            continue
        if needle and needle in _norm(fact.get("value") or ""):
            return True
    return False


def _ask(service: MemoryService, conv_id: str, question: str) -> dict:
    result = service.send_message(conv_id, question)
    answer = result["assistant"]["content"]
    route = result["route"]
    print(f"Q: {question}\nA: {answer}\nroute={route.get('label')} fired={route.get('fired')} reason={route.get('reason')}\n", flush=True)
    return result


def _teach(service: MemoryService, conversations: list[dict]) -> list[str]:
    ids = []
    for item in conversations:
        conv = service.create_conversation(item["title"])
        ids.append(conv["id"])
        for sentence in item["sentences"]:
            result = service.send_message(conv["id"], sentence)
            if result.get("proposal"):
                raise RuntimeError(f"教事实时弹出了纠正：{sentence}")
    return ids


def _score_language(service: MemoryService, spec: dict, language: str) -> dict:
    ids = _teach(service, spec[language])
    preview = service.preview_consolidation(ids)
    if "uncovered" not in preview:
        raise RuntimeError("预览没有返回未覆盖的句子")
    selected = [fact for fact in preview["facts"] if fact.get("selected")]
    planted = [value for convo in spec[language] for value, _rel in convo["facts"]]
    found = sum(1 for value in planted if _covered(value, selected))
    if planted and found / len(planted) < 0.95:
        raise RuntimeError(f"{language} 抽取 {found}/{len(planted)}，低于 95%")
    if any(convo["title"] and not any(_covered(value, selected) for value, _rel in convo["facts"]) for convo in spec[language]):
        empty = [convo["title"] for convo in spec[language] if not any(_covered(value, selected) for value, _rel in convo["facts"])]
        if empty and not preview.get("empty_sources"):
            raise RuntimeError(f"整段没抽出事实却没有提示：{empty}")
    job = service.start_consolidation(ids, selected, preview_id=preview["preview_id"])
    status = _wait(service, job["id"])
    if status.get("status") != "done":
        raise RuntimeError(status.get("error") or status.get("message") or "训练失败")
    if not status.get("saved_facts"):
        raise RuntimeError("完成状态没有保存事实列表")
    fresh = service.create_conversation()
    recall_hits = 0
    recall_rows = []
    for question, gold in spec[f"{language}_recall"]:
        result = _ask(service, fresh["id"], question)
        answer = result["assistant"]["content"]
        overview = "记住的是" in answer or "what i have stored" in answer.casefold()
        ok = bool(result["route"].get("fired") and _norm(gold) in _norm(answer) and not overview)
        recall_hits += int(ok)
        recall_rows.append({"q": question, "gold": gold, "answer": answer, "ok": ok})
    yes_hits = 0
    yes_rows = []
    for question, expect_yes, gold in spec[f"{language}_yes"]:
        result = _ask(service, fresh["id"], question)
        answer = result["assistant"]["content"].strip()
        if language == "zh":
            head = "是" if expect_yes else "不是"
            ok = answer.startswith(head) and (not expect_yes or _norm(gold) in _norm(answer))
        else:
            head = "yes" if expect_yes else "no"
            ok = answer.casefold().startswith(head)
        yes_hits += int(ok)
        yes_rows.append({"q": question, "answer": answer, "ok": ok})
    open_hits = 0
    open_rows = []
    for question, gold in spec.get(f"{language}_open", []):
        result = _ask(service, fresh["id"], question)
        answer = result["assistant"]["content"]
        reason = result["route"].get("reason")
        ok = reason == "entity_overview" and _norm(gold) in _norm(answer) and result["route"].get("label") != "基座"
        open_hits += int(ok)
        open_rows.append({"q": question, "answer": answer, "ok": ok, "reason": reason})
    near_hits = 0
    near_rows = []
    for question, forbidden in spec.get(f"{language}_near", []):
        result = _ask(service, fresh["id"], question)
        answer = result["assistant"]["content"]
        reason = result["route"].get("reason")
        leaked = _norm(forbidden) in _norm(answer)
        ok = (not leaked) and reason in {"entity_clarify", "entity_grounded"}
        near_hits += int(ok)
        near_rows.append({"q": question, "answer": answer, "ok": ok, "reason": reason})
    abstain_hits = 0
    wrong = 0
    stored_values = [_norm(value) for value in planted]
    for question in spec[f"{language}_abstain"]:
        result = _ask(service, fresh["id"], question)
        answer = result["assistant"]["content"]
        named = "不在记忆里" in answer or "not in memory" in answer.casefold()
        borrowed = _norm(answer).strip("。.") in stored_values
        if borrowed:
            wrong += 1
        abstain_hits += int(named and not borrowed)
    return {
        "extract": f"{found}/{len(planted)}",
        "recall": f"{recall_hits}/{len(spec[f'{language}_recall'])}",
        "recall_hits": recall_hits,
        "recall_total": len(spec[f"{language}_recall"]),
        "yes": f"{yes_hits}/{len(spec[f'{language}_yes'])}",
        "yes_hits": yes_hits,
        "yes_total": len(spec[f"{language}_yes"]),
        "abstain": f"{abstain_hits}/{len(spec[f'{language}_abstain'])}",
        "abstain_hits": abstain_hits,
        "abstain_total": len(spec[f"{language}_abstain"]),
        "wrong_attribute": wrong,
        "open": f"{open_hits}/{len(spec.get(f'{language}_open', []))}",
        "open_hits": open_hits,
        "open_total": len(spec.get(f"{language}_open", [])),
        "near": f"{near_hits}/{len(spec.get(f'{language}_near', []))}",
        "near_hits": near_hits,
        "near_total": len(spec.get(f"{language}_near", [])),
        "rows": recall_rows,
        "yes_rows": yes_rows,
        "open_rows": open_rows,
        "near_rows": near_rows,
        "message": status.get("message"),
    }


def _color_fact_id(service: MemoryService, person: str, color: str) -> str:
    needle = _norm(color)
    for record in service.expert_records():
        memory = getattr(record, "fact_memory", None) or {}
        for index, fact in enumerate(memory.get("facts") or []):
            if not isinstance(fact, dict) or fact.get("superseded"):
                continue
            if str(fact.get("entity") or "") != person:
                continue
            if needle and needle in _norm(fact.get("value") or ""):
                return str(fact.get("id") or f"{record.name}#{index}")
    raise RuntimeError(f"没有找到{person}的车颜色事实")


def _score_corrected_color(service: MemoryService, spec: dict) -> dict:
    """纠正并重新训练之后，颜色的几种问法要答出新取值。"""
    person = spec["en"][0]["title"]
    old = spec["en_color"]
    new = spec["en_color_next"]
    fact_id = _color_fact_id(service, person, old)
    utterance = f"{person}'s car is {new}."
    proposal = service.propose_correction(utterance, fact_id=fact_id, new_value=new)
    if not proposal or _norm(proposal.get("new_value")) != _norm(new):
        raise RuntimeError(f"车颜色纠正没有对上新取值：{proposal}")
    job = service.commit_correction(proposal)
    status = _wait(service, job["id"])
    if status.get("status") != "done":
        raise RuntimeError(status.get("error") or status.get("message") or "颜色纠正训练失败")
    fresh = service.create_conversation()
    hits = 0
    rows = []
    questions = [
        f"What color is {person}'s car?",
        f"What colour is {person}'s car?",
        f"What color does {person}'s car have?",
    ]
    for question in questions:
        result = _ask(service, fresh["id"], question)
        answer = result["assistant"]["content"]
        overview = "what i have stored" in answer.casefold()
        ok = bool(result["route"].get("fired") and _norm(new) in _norm(answer) and _norm(old) not in _norm(answer) and not overview)
        hits += int(ok)
        rows.append({"q": question, "answer": answer, "ok": ok})
    yes = _ask(service, fresh["id"], f"Is {person}'s car {new}?")
    yes_answer = yes["assistant"]["content"].strip()
    yes_ok = yes_answer.casefold().startswith("yes") and _norm(new) in _norm(yes_answer)
    print("CHAT_PATH_AFTER_CORR_COLOR", f"{hits}/{len(questions)}", flush=True)
    print("CHAT_PATH_AFTER_CORR_COLOR_YES", "1/1" if yes_ok else "0/1", flush=True)
    if hits != len(questions) or not yes_ok:
        raise RuntimeError(f"纠正后的颜色问法没有答出新取值：{rows} yes={yes_answer}")
    return {"color": f"{hits}/{len(questions)}", "yes": yes_ok, "rows": rows}


def run_chat_path(service: MemoryService, spec: dict | None = None) -> dict:
    spec = spec or build()
    zh = _score_language(service, spec, "zh")
    en = _score_language(service, spec, "en")
    probe = service.create_conversation()
    general_fired = 0
    for question in spec["general"]:
        result = _ask(service, probe["id"], question)
        if result["route"].get("fired"):
            general_fired += 1
    false_corrections = 0
    for sentence in spec["statements"]:
        result = _ask(service, probe["id"], sentence)
        if result.get("proposal"):
            false_corrections += 1
    report = {
        "seed": spec["seed"],
        "zh": zh,
        "en": en,
        "general_fired": general_fired,
        "general_total": len(spec["general"]),
        "false_corrections": false_corrections,
    }
    print("CHAT_PATH_EXTRACT_ZH", zh["extract"], flush=True)
    print("CHAT_PATH_EXTRACT_EN", en["extract"], flush=True)
    print("CHAT_PATH_RECALL_ZH", zh["recall"], flush=True)
    print("CHAT_PATH_RECALL_EN", en["recall"], flush=True)
    print("CHAT_PATH_YES", f"{zh['yes_hits'] + en['yes_hits']}/{zh['yes_total'] + en['yes_total']}", flush=True)
    print("CHAT_PATH_YES_ZH", zh["yes"], flush=True)
    print("CHAT_PATH_YES_EN", en["yes"], flush=True)
    print("CHAT_PATH_OPEN", f"{zh['open_hits'] + en['open_hits']}/{zh['open_total'] + en['open_total']}", flush=True)
    print("CHAT_PATH_NEAR", f"{zh['near_hits'] + en['near_hits']}/{zh['near_total'] + en['near_total']}", flush=True)
    print("CHAT_PATH_ABSTAIN", f"{zh['abstain_hits'] + en['abstain_hits']}/{zh['abstain_total'] + en['abstain_total']}", flush=True)
    print("CHAT_PATH_WRONG_ATTRIBUTE", zh["wrong_attribute"] + en["wrong_attribute"], flush=True)
    print("CHAT_PATH_FALSE_CORRECTION", false_corrections, flush=True)
    print("CHAT_PATH_GENERAL_FIRED", f"{general_fired}/{len(spec['general'])}", flush=True)
    zh_rate = zh["recall_hits"] / zh["recall_total"]
    en_rate = en["recall_hits"] / en["recall_total"]
    yes_total = zh["yes_total"] + en["yes_total"]
    yes_rate = (zh["yes_hits"] + en["yes_hits"]) / yes_total if yes_total else 1
    zh_yes_rate = zh["yes_hits"] / zh["yes_total"] if zh["yes_total"] else 1
    en_yes_rate = en["yes_hits"] / en["yes_total"] if en["yes_total"] else 1
    abstain_total = zh["abstain_total"] + en["abstain_total"]
    abstain_rate = (zh["abstain_hits"] + en["abstain_hits"]) / abstain_total if abstain_total else 1
    open_bad = (zh["open_total"] - zh["open_hits"]) + (en["open_total"] - en["open_hits"])
    near_bad = (zh["near_total"] - zh["near_hits"]) + (en["near_total"] - en["near_hits"])
    from memory_core.extract import uncovered_claims

    if not uncovered_claims(
        "北窗茶舍养了一只狗，名字叫阿黄。",
        [{"entity": "北窗茶舍", "value": "狗", "statement": "北窗茶舍养了一只狗。"}],
    ):
        raise RuntimeError("部分抽取没有标出可以手动补上的句子")
    if zh_rate < 0.90 or en_rate < 0.85 or zh_yes_rate < 0.90 or en_yes_rate < 0.90 or yes_rate < 0.90 or abstain_rate < 0.95:
        raise RuntimeError(
            f"对话路径没有达到目标：{report['zh']['recall']} {report['en']['recall']} "
            f"yes zh {zh_yes_rate:.2f} en {en_yes_rate:.2f} abstain {abstain_rate:.2f}"
        )
    if open_bad or near_bad:
        raise RuntimeError(f"开放题或近似名字没有守住：open {open_bad} near {near_bad}")
    if zh["wrong_attribute"] or en["wrong_attribute"] or false_corrections or general_fired:
        raise RuntimeError("对话路径出现了错属性、误纠正或常识题激活")
    report["after_color"] = _score_corrected_color(service, spec)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--models", type=Path, default=None)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()
    from memory_core.paths import default_models_dir

    service = MemoryService(
        home=args.home,
        models_dir=args.models or default_models_dir(),
        repo_experts=None,
        device=args.device,
        use_repo_experts=False,
    )
    service.ensure_ready()
    try:
        run_chat_path(service)
    except Exception as exc:
        print(f"CHAT_PATH_FAIL {exc}", flush=True)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()

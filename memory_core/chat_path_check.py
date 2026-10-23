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
        "rows": recall_rows,
        "yes_rows": yes_rows,
        "message": status.get("message"),
    }


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
    print("CHAT_PATH_ABSTAIN", f"{zh['abstain_hits'] + en['abstain_hits']}/{zh['abstain_total'] + en['abstain_total']}", flush=True)
    print("CHAT_PATH_WRONG_ATTRIBUTE", zh["wrong_attribute"] + en["wrong_attribute"], flush=True)
    print("CHAT_PATH_FALSE_CORRECTION", false_corrections, flush=True)
    print("CHAT_PATH_GENERAL_FIRED", f"{general_fired}/{len(spec['general'])}", flush=True)
    zh_rate = zh["recall_hits"] / zh["recall_total"]
    en_rate = en["recall_hits"] / en["recall_total"]
    yes_total = zh["yes_total"] + en["yes_total"]
    yes_rate = (zh["yes_hits"] + en["yes_hits"]) / yes_total if yes_total else 1
    abstain_total = zh["abstain_total"] + en["abstain_total"]
    abstain_rate = (zh["abstain_hits"] + en["abstain_hits"]) / abstain_total if abstain_total else 1
    if zh_rate < 0.90 or en_rate < 0.85 or yes_rate < 0.90 or abstain_rate < 0.95:
        raise RuntimeError(f"对话路径没有达到目标：{report['zh']['recall']} {report['en']['recall']} yes {yes_rate:.2f} abstain {abstain_rate:.2f}")
    if zh["wrong_attribute"] or en["wrong_attribute"] or false_corrections or general_fired:
        raise RuntimeError("对话路径出现了错属性、误纠正或常识题激活")
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

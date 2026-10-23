#!/usr/bin/env python3
"""展开桌面同一套巩固样本,并写出手机基准用的事实。

4 条研究事实,每条只把用户确认的那一问放进训练,其余问法留给闸门或留作没训练过的复述。
训练程序还会为每条事实加一行「请说出这条事实。」。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


TRAILING = ("最喜欢", "比较喜欢", "非常喜欢", "喜欢", "现在的", "目前的")


def has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def finish_statement(raw: str) -> str:
    text = raw.strip()
    if not text or text[-1] in "。！？.!?":
        return text
    return text + ("。" if has_cjk(text) else ".")


def attr_question(entity: str, attr: str, tail: str) -> str:
    glued = any(attr.startswith(suffix + "的") for suffix in TRAILING)
    joiner = "" if glued else "的"
    return f"{entity}{joiner}{attr}{tail}"


def expand(fact: dict) -> dict:
    english = not has_cjk(f"{fact.get('entity','')}{fact.get('attr','')}{fact.get('value','')}{fact.get('statement','')}")
    attr = str(fact.get("attr") or "").strip() or ("fact" if english else "事实")
    value = str(fact.get("value") or "").strip()
    statement = finish_statement(str(fact.get("statement") or "").strip() or (
        f"{fact.get('entity')}'s {attr} is {value}." if english else f"{fact.get('entity')}的{attr}是{value}。"
    ))
    questions = []
    for qa in fact.get("qa") or []:
        q = str(qa.get("q") or "").strip()
        if q:
            questions.append(q)
    entity = fact.get("entity") or ""
    if english:
        if not questions:
            questions.append(f"What is {entity}'s {attr}?")
        questions.extend([
            f"What is {entity}'s {attr}?",
            f"What is the {attr} of {entity}?",
            f"Could you tell me {entity}'s {attr}?",
            f"Do you know {entity}'s {attr}?",
            f"Please tell me the {attr} of {entity}.",
        ])
        if attr in {"address", "where they live"} or "lives in" in statement.lower():
            questions.extend([
                f"Where does {entity} live?",
                f"Where is {entity}'s home?",
                f"What is {entity}'s address?",
            ])
        if "name" in attr.lower() or " named " in f" {statement.lower()} ":
            questions.extend([
                f"What is {entity}'s {attr} called?",
                f"Who is {entity}'s {attr}?",
            ])
    else:
        if not questions:
            questions.append(attr_question(entity, attr, "是什么？"))
        questions.extend([
            attr_question(entity, attr, "是什么？"),
            "请问" + attr_question(entity, attr, "是什么？"),
            "能告诉我" + attr_question(entity, attr, "吗？"),
            "你知道" + attr_question(entity, attr, "吗？"),
            f"{entity}{attr}是什么？",
            f"关于{entity}，{attr}是什么？",
        ])
        if "住" in attr or "住在" in statement:
            questions.extend([
                f"{entity}住在哪里？",
                f"{entity}住在什么地方？",
                f"请问{entity}的住址是哪里？",
            ])
        if "叫" in statement or "名" in attr:
            questions.extend([
                f"{entity}的{attr}叫什么？",
                f"{entity}的{attr}是谁？",
            ])
    seen = set()
    qa = []
    for question in questions:
        question = question.strip()
        if not question or question in seen:
            continue
        seen.add(question)
        qa.append({"q": question, "a": value})
    out = dict(fact)
    out.update(attr=attr, value=value, statement=statement, qa=qa)
    return out


def load_confirmed(path: Path, n: int = 4) -> list[dict]:
    facts = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if len(facts) >= n:
                break
            row = json.loads(line)
            facts.append({
                "id": row["id"],
                "entity": row["entity"],
                "attr": row["attr"],
                "value": row["value"],
                "statement": row["statement"],
                "qa": [row["qa"][0]],
                "held_out": row["qa"][3],
                "selected": True,
            })
    return facts


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "data" / "batch_0.jsonl"
    confirmed = load_confirmed(source)
    expanded = [expand({k: v for k, v in fact.items() if k != "held_out"}) for fact in confirmed]
    # 闸门改写不进训练。这里放一条桌面会交给事实闸的说法,和留出的复述不是同一句。
    for fact, raw in zip(expanded, confirmed):
        fact["gate_questions"] = [raw["held_out"]["q"].replace("什么时候", "何时").replace("哪个地方", "何处")]
    rows = 0
    for fact in expanded:
        rows += 1 + len(fact["qa"])
    held = []
    trained_q = {qa["q"] for fact in expanded for qa in fact["qa"]}
    for raw in confirmed:
        q = raw["held_out"]["q"]
        if q in trained_q:
            raise SystemExit(f"留出问句被写进了训练: {q}")
        held.append({"q": q, "a": raw["held_out"]["a"], "id": raw["id"]})
    steps = (rows + 7) // 8
    report = {
        "n_facts": len(expanded),
        "n_samples": rows,
        "steps_per_epoch_accum8": steps,
        "epochs": 4,
        "optimizer_steps": steps * 4,
        "primary": [fact["qa"][0] for fact in expanded],
        "held_out": held,
    }
    text = json.dumps({"report": report, "facts": expanded, "held_out": held,
                       "never_written": ["一年有多少个月?", "法国的首都是哪里?"]}, ensure_ascii=False, indent=2)
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

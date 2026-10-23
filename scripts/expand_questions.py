"""写入时用基座模型为一条事实补几种不同问法。

提示里不写属性类别,也不给评测用的问法当例子。补出来的问法若和留出评测题
在去掉实体名、标点之后完全一样,就丢掉,避免把考题写进事实库。
"""
import argparse
import json
import os
import re
import time
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

ROOT = Path(__file__).resolve().parents[1]
MASK = "某"
_PUNCT = " \t\n\r？?。，,：:、！!；;「」\"'“”‘’（）()"


def _norm(text: str) -> str:
    return "".join(ch for ch in text if ch not in _PUNCT)


def _strip_number(line: str) -> str:
    return re.sub(r"^\s*(?:\d+[.、．)]|[-*•])\s*", "", line).strip()


def heldout_norms() -> set[str]:
    """留出评测题,实体换成占位符。调参用的 CEO/年份 PARA 不在这里。"""
    from eval_entity_guard_realistic import (
        COLLOQUIAL_TEMPLATES,
        LONG_TEMPLATES,
        ORG_TEMPLATES,
        TITLE_TEMPLATES,
        TWO_TEMPLATES,
    )
    from gen_data import OPEN_DOMAIN, PARA_QUESTIONS

    texts = []
    for group in (ORG_TEMPLATES, TITLE_TEMPLATES, COLLOQUIAL_TEMPLATES, LONG_TEMPLATES, TWO_TEMPLATES):
        for tmpl in group:
            texts.append(tmpl.format(e=MASK, d="另一"))
    for attr in ("总部城市", "旗舰产品"):
        for tmpl in PARA_QUESTIONS[attr]:
            texts.append(tmpl.format(e=MASK))
    for spec in OPEN_DOMAIN.values():
        for tmpl in spec["held"]:
            texts.append(tmpl.format(e=MASK))
    return {_norm(text) for text in texts}


def load_model(model_path: str, device: str):
    tok = AutoTokenizer.from_pretrained(model_path)
    model = AutoModelForCausalLM.from_pretrained(model_path, torch_dtype=torch.float32).to(device)
    model.eval()
    return tok, model


_LABEL = re.compile(r"^(?:原问题|原问法|原问|新问题|新问法|新问|陈述|问法|问题|改写)\s*[：:]\s*")


def _generate_batch(model, tok, device: str, prompts: list[str], seed: int) -> list[str]:
    """一次改写一句。左填充,这样批量解码时新词都从同一位置开始。"""
    if not prompts:
        return []
    texts = []
    for prompt in prompts:
        messages = [
            {"role": "system", "content": "你是助手。"},
            {"role": "user", "content": prompt},
        ]
        texts.append(tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True))
    tok.padding_side = "left"
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token
    torch.manual_seed(seed)
    inputs = tok(texts, return_tensors="pt", padding=True).to(device)
    with torch.no_grad():
        out = model.generate(
            **inputs,
            max_new_tokens=48,
            do_sample=True,
            temperature=0.8,
            top_p=0.9,
            pad_token_id=tok.pad_token_id,
        )
    prompt_len = inputs["input_ids"].shape[1]
    decoded = []
    for row in out:
        decoded.append(tok.decode(row[prompt_len:], skip_special_tokens=True).strip())
    return decoded


def prompt_one(fact: dict, question: str) -> str:
    """只给这条事实的陈述句和其中一句已有问法。不列举属性,不给评测题。"""
    return (
        f"事实：{fact['statement']}\n"
        f"原问法：{question}\n"
        "请把原问法换成另一种说法：尽量用不同的词，但还是在问同一件事，而且只能靠这条事实回答。"
        "只写一个新问题，不要编号，不要解释。"
    )


def prompt_for(fact: dict, n: int) -> str:
    """供提示词泄漏检查。正式生成走 prompt_one,逐句改写。"""
    questions = [qa["q"] for qa in fact.get("qa") or []]
    return prompt_one(fact, questions[0] if questions else "问")


def _clean_line(raw: str) -> str:
    line = raw.splitlines()[0] if raw else ""
    line = _strip_number(line)
    line = _LABEL.sub("", line).strip()
    line = line.strip("「」\"'")
    return line


def _accept_line(question: str, entity: str, seen: set[str], blocked: set[str]) -> bool:
    if not question or entity not in question:
        return False
    if any(token in question for token in ("是否", "是不是", "对不对", "对吗", "不知道")):
        return False
    if not any(mark in question for mark in ("?", "？", "吗", "谁", "哪", "什么", "多少", "几")):
        return False
    key = _norm(question)
    if key in seen or key in blocked or len(key) < 6 or len(question) > 40:
        return False
    return True


def expand_one(model, tok, device: str, fact: dict, n: int, seed: int, blocked: set[str]) -> tuple[list[str], list[str]]:
    questions = [qa["q"] for qa in fact.get("qa") or []]
    prompts = [prompt_one(fact, question) for question in questions[:n]]
    raws = _generate_batch(model, tok, device, prompts, seed)
    entity = fact["entity"]
    seen = {_norm(qa["q"]) for qa in fact.get("qa") or []}
    seen.add(_norm(fact["statement"]))
    kept = []
    cleaned = []
    for raw in raws:
        question = _clean_line(raw)
        cleaned.append(question)
        if not _accept_line(question, entity, seen, blocked):
            continue
        seen.add(_norm(question))
        kept.append(question)
    return kept, cleaned


def edits_within(left: str, right: str, limit: int = 2) -> bool:
    """编辑距离不超过 limit。长度差已经更大时直接否掉。"""
    if abs(len(left) - len(right)) > limit:
        return False
    prev = list(range(len(right) + 1))
    for i, ca in enumerate(left, start=1):
        cur = [i]
        best = i
        for j, cb in enumerate(right, start=1):
            val = min(cur[j - 1] + 1, prev[j] + 1, prev[j - 1] + (ca != cb))
            cur.append(val)
            if val < best:
                best = val
        if best > limit:
            return False
        prev = cur
    return prev[-1] <= limit


def heldout_leak(question: str, entity: str, blocked: set[str]) -> str | None:
    """和留出评测题相同,或只差两字以内,或把留出题原样包了一层。"""
    masked = _norm(question.replace(entity, MASK))
    if masked in blocked:
        return "exact"
    for item in blocked:
        if len(item) >= 8 and item in masked:
            return "wrap"
        if len(item) >= 8 and edits_within(masked, item, 3):
            return "edit3"
    return None


def assign_group_paraphrases(rows: list[dict]) -> dict[str, list[str]]:
    """同一条改写若被几种不同的陈述句生成,只留给生成它的实体最多的那一种。

    平局就丢掉。留下之后,这种陈述句下的每个实体都带上这些问句。
    掩码后原文相同才算同一条,不看属性名字。
    """
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row["statement_masked"], []).append(row)
    # masked question -> statement -> (source entity, surface question, entity set)
    bucket: dict[str, dict[str, dict]] = {}
    for statement, members in groups.items():
        for row in members:
            for question in row["paraphrases"]:
                masked = _norm(question.replace(row["entity"], MASK))
                slot = bucket.setdefault(masked, {}).setdefault(statement, {"entities": set(), "example": question, "src": row["entity"]})
                slot["entities"].add(row["entity"])
    chosen: dict[str, list[tuple[str, str]]] = {statement: [] for statement in groups}
    for _masked, by_stmt in bucket.items():
        ranked = sorted(by_stmt.items(), key=lambda item: len(item[1]["entities"]), reverse=True)
        if len(ranked) >= 2 and len(ranked[0][1]["entities"]) == len(ranked[1][1]["entities"]):
            continue
        statement, slot = ranked[0]
        chosen[statement].append((slot["src"], slot["example"]))
    out: dict[str, list[str]] = {}
    for statement, members in groups.items():
        for row in members:
            retargeted = []
            seen = set()
            for src, question in chosen.get(statement, []):
                text = question.replace(src, row["entity"])
                key = _norm(text)
                if key in seen or row["entity"] not in text:
                    continue
                seen.add(key)
                retargeted.append(text)
            out[row["entity"]] = retargeted
    return out


def _facts_from_batches(data_dir: Path) -> list[dict]:
    facts = []
    for path in sorted(data_dir.glob("batch_*.jsonl")):
        for line in path.open(encoding="utf-8"):
            if line.strip():
                fact = json.loads(line)
                fact["batch"] = int(path.stem.split("_")[1])
                facts.append(fact)
    return facts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=str(ROOT / "models" / "Qwen2.5-0.5B-Instruct"))
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    parser.add_argument("--open", type=Path, default=ROOT / "data_heldout" / "open_domain.jsonl")
    parser.add_argument("--experts", type=Path, default=ROOT / "experts")
    parser.add_argument("--n", type=int, default=6, help="每条事实最多改写几句已有问法")
    parser.add_argument("--limit", type=int, default=0, help="每种属性只跑一条,用来看生成质量")
    parser.add_argument("--seed", type=int, default=20261022)
    parser.add_argument("--sidecar", type=Path, default=None, help="把改写结果另存,不写 fact_memory.json")
    args = parser.parse_args()

    blocked = heldout_norms()
    # 提示词本身不能带评测题。陈述句里的词不算。
    boilerplate = prompt_for({"statement": "事实", "qa": [{"q": "问"}], "entity": "名"}, args.n)
    leaked_prompt = [item for item in blocked if item and item in _norm(boilerplate)]
    if leaked_prompt:
        raise SystemExit(f"提示词里混进了留出评测题: {leaked_prompt[:3]}")

    facts = _facts_from_batches(args.data)
    open_facts = [json.loads(line) for line in args.open.open(encoding="utf-8") if line.strip()]
    work = facts + open_facts
    if args.limit:
        # 每种属性取一条,避免试点全挤在同一类上。
        picked = []
        seen_attr = set()
        for fact in work:
            if fact["attr"] not in seen_attr:
                picked.append(fact)
                seen_attr.add(fact["attr"])
        work = picked[:args.limit]

    device = "cpu"
    torch.set_num_threads(int(os.environ.get("OMP_NUM_THREADS", "4")))
    tok, model = load_model(args.model, device)
    started = time.perf_counter()
    dropped = []
    for index, fact in enumerate(work):
        t0 = time.perf_counter()
        raw_seed = args.seed + index
        # 先不拦评测题,记下会被丢掉的,再正式过滤。
        draft, cleaned = expand_one(model, tok, device, fact, args.n, raw_seed, blocked=set())
        fact["para_raw"] = cleaned
        removed = []
        kept = []
        for question in draft:
            reason = heldout_leak(question, fact["entity"], blocked)
            if reason:
                removed.append(f"{reason}:{question}")
            else:
                kept.append(question)
        fact["paraphrases"] = kept
        dt = time.perf_counter() - t0
        if removed:
            dropped.append((fact["entity"], fact["attr"], removed))
        print(
            f"{fact['entity']} [{fact['attr']}] 保留 {len(kept)} 丢掉 {len(removed)} {dt:.1f}s",
            flush=True,
        )
        for question in kept:
            print(f"  + {question}", flush=True)
        for question in removed:
            print(f"  - 与留出题相同,已丢 {question}", flush=True)
        if args.limit:
            kept_set = set(kept) | set(removed)
            for question in cleaned:
                if question not in kept_set:
                    print(f"  . 未保留 {question}", flush=True)
    elapsed = time.perf_counter() - started
    print(
        f"共 {len(work)} 条,用时 {elapsed:.0f}s,平均 {elapsed / max(len(work), 1):.2f}s/条,"
        f"因与留出评测题相同而丢掉 {sum(len(item[2]) for item in dropped)} 句",
        flush=True,
    )
    if args.sidecar:
        args.sidecar.parent.mkdir(parents=True, exist_ok=True)
        args.sidecar.write_text(
            "".join(json.dumps({
                "entity": fact["entity"],
                "attr": fact.get("attr", ""),
                "statement": fact["statement"],
                "paraphrases": fact.get("paraphrases") or [],
            }, ensure_ascii=False) + "\n" for fact in work),
            encoding="utf-8",
        )
        print(f"写入 {args.sidecar}", flush=True)
    if args.limit or args.sidecar:
        return

    by_batch: dict[int, list[dict]] = {}
    for fact in facts:
        by_batch.setdefault(fact["batch"], []).append(fact)
    for batch, group in by_batch.items():
        path = args.experts / f"expert_{batch}" / "fact_memory.json"
        records = []
        for fact in group:
            records.append({
                "entity": fact["entity"],
                "value": fact.get("value", ""),
                "statement": fact["statement"],
                "questions": [qa["q"] for qa in fact["qa"]],
                "paraphrases": fact.get("paraphrases") or [],
            })
        path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"写入 {path}", flush=True)
    args.open.write_text(
        "".join(json.dumps(fact, ensure_ascii=False) + "\n" for fact in open_facts),
        encoding="utf-8",
    )
    print(f"写入 {args.open}", flush=True)


if __name__ == "__main__":
    main()

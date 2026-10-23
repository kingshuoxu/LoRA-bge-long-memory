"""对比事实闸的四种做法:不改、写入时改写问句、窄带交叉编码器、两者一起。

阈值和窄带只从 CEO / 成立年份的 PARA 问法上取,见 calibrate 的调参输出。
留出问法、留出属性、开放域不参与取切分。
"""
import argparse
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).parent))

from eval_entity_guard_realistic import (  # noqa: E402
    DATA_PATH,
    HELD_ATTRS,
    TUNE_ATTRS,
    _asked_attr,
    _norm_key,
    _row_fact,
    load_expert_entities,
    load_facts,
    load_rows,
    regression_rows,
    route_decision,
)
from expand_questions import (  # noqa: E402
    _accept_line,
    _clean_line,
    _norm,
    assign_group_paraphrases,
    heldout_leak,
    heldout_norms,
)
from gen_data import OPEN_DOMAIN  # noqa: E402
from router import (  # noqa: E402
    FactMemory,
    FactReranker,
    embed,
    load_fact_gate,
    load_fact_records,
)

TUNE_JSON = Path("/tmp/rerank_tune.json")
RAW_PARA = Path("/tmp/para_raw.jsonl")
GEN_JSON = Path("/tmp/guard_fact_generate.json")


def _dist(own: float, other: float, tau: float) -> float:
    gap_tau = own - tau
    gap_other = own - other
    if gap_tau >= 0 and gap_other >= 0:
        return min(gap_tau, gap_other)
    short = 0.0
    if gap_tau < 0:
        short = max(short, -gap_tau)
    if gap_other < 0:
        short = max(short, -gap_other)
    return -short


def _bi(own: float, other: float, tau: float) -> bool:
    return own >= tau and own + 1e-6 >= other


def freeze_reranker(path: Path) -> dict:
    """只看调参行,定 passage / cut / delta。定完就不再改。

    双边复议会把「老大」从 CEO 事实上拿掉(陈述句得分 -1.41,年份陈述句 2.98),
    所以窄带只用来捞回双编码器拒绝的问句,不推翻已经接受的。
    切分取 PARA 正例里「胜过另一条」的最低陈述句得分。
    带宽用留一问法的最大落差,这一步在看交叉编码器分数之前就定了。
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    tau = float(data["meta"]["tau"])
    loo = float(data["meta"]["loo_delta"])
    rows = [row for row in data["rows"] if row["label"] in ("para_pos", "para_neg", "canon_pos", "canon_neg")]
    winners = [row["r_stmt"] for row in rows if row["label"] == "para_pos" and row["r_stmt"] >= row["r_stmt_other"]]
    losers = [row for row in rows if row["label"] == "para_pos" and row["r_stmt"] < row["r_stmt_other"]]
    neg_beat = [row["r_stmt"] for row in rows if row["label"] == "para_neg" and row["r_stmt"] >= row["r_stmt_other"]]
    cut = min(winners)
    delta = loo

    def predict(row: dict) -> bool:
        bi = _bi(row["own"], row["other"], tau)
        if bi:
            return True
        if abs(_dist(row["own"], row["other"], tau)) > delta + 1e-9:
            return False
        return row["r_stmt"] >= cut and row["r_stmt"] + 1e-6 >= row["r_stmt_other"]

    bad = []
    for row in rows:
        truth = row["label"].endswith("pos")
        if predict(row) != truth:
            bad.append(row["label"])
    print("调参集上冻结交叉编码器(还没看留出题):", flush=True)
    print(
        f"  陈述句。双边复议会否掉 PARA 正例 {len(losers)} 条(全是「老大」)。"
        f"因此只复议双编码器的拒绝。",
        flush=True,
    )
    print(
        f"  delta={delta:.4f}(留一落差) cut={cut:.4f} "
        f"负例里胜过另一条的最高分 {max(neg_beat):.4f}",
        flush=True,
    )
    print(f"  这条规则在调参行上的不一致 {len(bad)} {bad[:6]}", flush=True)
    if bad:
        raise SystemExit("冻结规则没有保住调参集")
    return {
        "passage": "statement",
        "delta": delta,
        "cut": cut,
        "tau": tau,
        "loo_delta": loo,
        "upgrade_only": True,
    }


def _masked_statement(memory: FactMemory, record: dict) -> str:
    value = str(record.get("value", "")).rstrip("年")
    return memory._mask_fact(str(record["statement"]), str(record["entity"]), value)


def load_raw(path: Path) -> list[dict]:
    rows = []
    for line in path.open(encoding="utf-8"):
        if line.strip():
            rows.append(json.loads(line))
    return rows


_LATIN = re.compile(r"[A-Za-z]{2,}")


def apply_leak_filter(raw_rows: list[dict], blocked: set[str], allowed: dict[str, str] | None = None) -> tuple[list[dict], dict]:
    """丢掉和留出评测题相同或几乎相同的改写。这一步不看对错,只防泄题。"""
    stats = defaultdict(int)
    cleaned = []
    examples = []
    for row in raw_rows:
        kept = []
        seen = set()
        for question in row.get("paraphrases") or []:
            question = _clean_line(question)
            if not _accept_line(question, row["entity"], seen, set()):
                stats["format"] += 1
                continue
            seen.add(_norm(question))
            extra = _LATIN.findall(question)
            known = set(_LATIN.findall((allowed or {}).get(row["entity"], "")))
            if any(token.upper() not in {item.upper() for item in known} for token in extra):
                stats["latin"] += 1
                if len(examples) < 20:
                    examples.append(f"latin {row['entity']} {question}")
                continue
            reason = heldout_leak(question, row["entity"], blocked)
            stats["seen"] += 1
            if reason:
                stats[reason] += 1
                if len(examples) < 20:
                    examples.append(f"{reason} {row['entity']} {question}")
                continue
            stats["kept_leak"] += 1
            kept.append(question)
        cleaned.append({**row, "paraphrases": kept})
    stats["examples"] = examples
    return cleaned, stats


def _mask_para(memory: FactMemory, question: str, entity: str) -> str:
    masked = memory.mask_query(question)
    if entity and entity in masked:
        masked = masked.replace(entity, memory.mask)
    return masked


def score_paraphrases(memory: FactMemory, rows: list[dict], reranker: FactReranker, prototypes: list[str]) -> list[dict]:
    """每句改写对每条原型陈述打分。原型是掩码后的陈述句,同一属性只留一条。"""
    pairs = []
    index = {}
    for row in rows:
        for question in row["paraphrases"]:
            masked = _mask_para(memory, question, row["entity"])
            for proto in prototypes:
                key = (masked, proto)
                if key not in index:
                    index[key] = len(pairs)
                    pairs.append(key)
    print(f"改写问句对原型陈述 {len(pairs)} 对", flush=True)
    started = time.perf_counter()
    scores = reranker.score(pairs) if pairs else []
    print(f"  打分 {time.perf_counter() - started:.1f}s", flush=True)
    scored = []
    for row in rows:
        own = row["statement_masked"]
        kept_rel = []
        kept_abs = []
        detail = []
        for question in row["paraphrases"]:
            masked = _mask_para(memory, question, row["entity"])
            own_s = scores[index[(masked, own)]]
            other_s = max(scores[index[(masked, proto)]] for proto in prototypes if proto != own)
            detail.append((question, own_s, other_s))
            if own_s >= other_s:
                kept_rel.append(question)
                if own_s >= reranker.cut:
                    kept_abs.append(question)
        scored.append({**row, "detail": detail, "rel": kept_rel, "abs": kept_abs})
    return scored


def tune_filter_report(scored: list[dict], facts_by_entity: dict[str, dict]) -> None:
    """只打印 CEO / 成立年份上的改写去留。用这个决定过滤器,不看城市和产品。"""
    print("调参属性上的改写过滤(决定 A 用哪一档,还没看留出属性):", flush=True)
    for mode in ("rel", "abs"):
        kept_n = 0
        total = 0
        founder_ceo = founder_year = cfo = why = 0
        for row in scored:
            fact = facts_by_entity.get(row["entity"])
            if fact is None or fact["attr"] not in TUNE_ATTRS:
                continue
            total += len(row["paraphrases"])
            kept_n += len(row[mode])
            for question in row[mode]:
                if "创始人" in question and fact["attr"] == "CEO":
                    founder_ceo += 1
                if "创始人" in question and fact["attr"] == "成立年份":
                    founder_year += 1
                if "CFO" in question.upper() or "财务" in question:
                    cfo += 1
                if "为什么" in question or "为啥" in question:
                    why += 1
        print(
            f"  {mode}: 留下 {kept_n}/{total}  CEO上含创始人 {founder_ceo}  "
            f"年份上含创始人 {founder_year}  含CFO/财务 {cfo}  含为什么 {why}",
            flush=True,
        )
    print("  CEO / 年份上被绝对切分丢掉、但相对比较留下的例子:", flush=True)
    shown = 0
    for row in scored:
        fact = facts_by_entity.get(row["entity"])
        if fact is None or fact["attr"] not in TUNE_ATTRS:
            continue
        rel_only = [q for q in row["rel"] if q not in row["abs"]]
        for question in rel_only:
            if shown >= 12:
                break
            own_s, other_s = next((a, b) for q, a, b in row["detail"] if q == question)
            print(f"    {fact['attr']} {own_s:.2f}/{other_s:.2f} {question}", flush=True)
            shown += 1


def drop_tune_thieves(memory: FactMemory, by_entity: dict[str, list[str]], prepared: list[dict]) -> dict[str, list[str]]:
    """改写如果比调参正例更靠近错误的那条事实,就丢掉。

    只看 CEO / 成立年份的 PARA 问法。留出问法不参与。
    """
    from gen_data import PARA_QUESTIONS

    entity_stmt = {row["entity"]: row["statement_masked"] for row in prepared}
    stmt_entity: dict[str, str] = {}
    for row in prepared:
        if row["entity"] in memory._spans:
            stmt_entity.setdefault(row["statement_masked"], row["entity"])
    sample = next(entity for entity in entity_stmt if entity in memory._spans)
    tune_qs = []
    for attr in TUNE_ATTRS:
        for tmpl in PARA_QUESTIONS[attr]:
            tune_qs.append(memory.mask_query(tmpl.format(e=sample)))
    gold_own = []
    gold_stmt = []
    for query in tune_qs:
        best_score = -1.0
        best_stmt = ""
        for statement, entity in stmt_entity.items():
            own, _other = memory.scores(query, entity)
            if own > best_score:
                best_score = own
                best_stmt = statement
        gold_own.append(best_score)
        gold_stmt.append(best_stmt)
        print(f"  调参问法 own={best_score:.3f} {query}", flush=True)

    masked_of: dict[tuple[str, str], str] = {}
    unique: list[str] = []
    seen = set()
    for entity, questions in by_entity.items():
        for question in questions:
            masked = _mask_para(memory, question, entity)
            masked_of[(entity, question)] = masked
            if masked not in seen:
                seen.add(masked)
                unique.append(masked)
    if not unique:
        return by_entity
    from router import embed

    sim = embed(tune_qs) @ embed(unique).T
    index = {text: i for i, text in enumerate(unique)}
    dropped = 0
    kept_n = 0
    new: dict[str, list[str]] = {}
    for entity, questions in by_entity.items():
        statement = entity_stmt[entity]
        kept = []
        for question in questions:
            masked = masked_of[(entity, question)]
            column = index[masked]
            steal = False
            for qi, (own, gstmt) in enumerate(zip(gold_own, gold_stmt)):
                if statement != gstmt and float(sim[qi, column]) > own + 1e-6:
                    steal = True
                    break
            if steal:
                dropped += 1
            else:
                kept.append(question)
                kept_n += 1
        new[entity] = kept
    print(f"  调参正例上会抢错事实的改写丢掉 {dropped} 条,留下 {kept_n} 条", flush=True)
    return new


def attach_paraphrases(records: list[dict], by_entity: dict[str, list[str]]) -> list[dict]:
    merged = []
    for record in records:
        item = dict(record)
        extra = by_entity.get(item["entity"])
        if extra:
            item["paraphrases"] = extra
        merged.append(item)
    return merged


def collect_pairs(rows: list[dict], facts: list[dict]) -> tuple[list[tuple[str, str]], list[str]]:
    from gen_data import PARA_QUESTIONS

    facts_by_id = {fact["id"]: fact for fact in facts}
    by_attr: dict[str, dict] = {}
    for fact in facts:
        by_attr.setdefault(fact["attr"], fact)
    pairs: list[tuple[str, str]] = []
    labels: list[str] = []

    def add(label: str, question: str, entity: str) -> None:
        pairs.append((question, entity))
        labels.append(label)

    for row in rows:
        if row["expect"] != "admit" or not row.get("entity"):
            continue
        fact, _index = _row_fact(row, facts_by_id)
        if fact is None:
            continue
        comparing = row["category"] == "two_entity" and ("相比" in row["q"] or "比较" in row["q"])
        if comparing:
            add("compare", row["q"], row["entity"])
            continue
        if row["category"] in ("canonical", "para"):
            asked = fact["attr"]
        else:
            asked = _asked_attr(row)
        if asked is None:
            add(f"no_unique:{row['category']}", row["q"], row["entity"])
            continue
        stored = asked == fact["attr"]
        if row["category"] == "canonical":
            label = "canonical"
        elif row["category"] == "para" and fact["attr"] in TUNE_ATTRS:
            label = "tune_para"
        elif row["category"] == "para":
            label = "held_attr_para"
        elif fact["attr"] in TUNE_ATTRS and asked in TUNE_ATTRS:
            label = "held_phrase"
        elif asked in HELD_ATTRS or fact["attr"] in HELD_ATTRS:
            label = "held_attr"
        else:
            label = "other"
        kind = f"{label}:{'stored' if stored else 'unstored'}"
        add(kind, row["q"], row["entity"])
        if "创始人是哪一位" in row["q"] and kind == "held_phrase:stored":
            add("founder_template:stored", row["q"], row["entity"])
        if row["category"] == "title" and stored:
            add("title_stored_all", row["q"], row["entity"])
        if row["category"] == "title" and not stored and asked:
            add("title_unstored_all", row["q"], row["entity"])

    for attr in TUNE_ATTRS:
        fact = by_attr[attr]
        other = next(name for name in TUNE_ATTRS if name != attr)
        for tmpl in PARA_QUESTIONS[other]:
            add("tune_neg", tmpl.format(e=fact["entity"]), fact["entity"])
    return pairs, labels


def summarize_decisions(name: str, labels: list[str], decided: list[tuple[bool, float, float]]) -> dict[str, tuple[int, int]]:
    grouped: dict[str, list[bool]] = defaultdict(list)
    for label, (ok, _own, _other) in zip(labels, decided):
        grouped[label].append(ok)
    print(f"\n== {name} ==", flush=True)
    order = [
        "canonical:stored",
        "tune_para:stored",
        "tune_neg",
        "held_phrase:stored",
        "founder_template:stored",
        "held_phrase:unstored",
        "held_attr_para:stored",
        "held_attr:stored",
        "held_attr:unstored",
        "title_stored_all",
        "title_unstored_all",
        "compare",
        "no_unique:title",
        "no_unique:colloquial",
    ]
    out = {}
    for label in order:
        flags = grouped.get(label)
        if not flags:
            continue
        abstain = label in ("tune_neg", "compare") or label.endswith("unstored") or label.startswith("no_unique")
        if abstain:
            good = sum(not flag for flag in flags)
            word = "弃权"
        else:
            good = sum(flags)
            word = "接受"
        out[label] = (good, len(flags))
        print(f"  {label:24s} {word} {good}/{len(flags)}", flush=True)
    return out


def open_domain_counts(
    memory: FactMemory,
    train_memory: FactMemory,
    facts: list[dict],
    open_facts: list[dict],
) -> dict[str, tuple[int, int]]:
    """在库的正负例走带开放域事实的库。未见关系只问旧实体,库里没有这 100 条新事实。"""
    pos_pairs = []
    for fact in open_facts:
        for tmpl in OPEN_DOMAIN[fact["attr"]]["held"]:
            pos_pairs.append((tmpl.format(e=fact["entity"]), fact["entity"]))
    neg_pairs = []
    old_probes = ["{e}公司的CEO是谁?", "{e}公司是哪一年成立的?", "{e}公司的总部在哪里?", "{e}公司的旗舰产品是什么?"]
    for fact in open_facts:
        for attr, spec in OPEN_DOMAIN.items():
            if attr == fact["attr"]:
                continue
            neg_pairs.append((spec["held"][0].format(e=fact["entity"]), fact["entity"]))
        for tmpl in old_probes:
            neg_pairs.append((tmpl.format(e=fact["entity"]), fact["entity"]))
    by_attr = {}
    for fact in facts:
        by_attr.setdefault(fact["attr"], fact)
    bare_pairs = []
    for fact in by_attr.values():
        for spec in OPEN_DOMAIN.values():
            for tmpl in spec["held"]:
                bare_pairs.append((tmpl.format(e=fact["entity"]), fact["entity"]))
    pos = memory.decide_many(pos_pairs)
    neg = memory.decide_many(neg_pairs)
    bare = train_memory.decide_many(bare_pairs)
    return {
        "open_pos": (sum(ok for ok, _, _ in pos), len(pos)),
        "open_neg": (sum(not ok for ok, _, _ in neg), len(neg)),
        "unseen": (sum(not ok for ok, _, _ in bare), len(bare)),
    }


def generation_counts(records: list[dict], entities, keys, memory: FactMemory | None) -> dict:
    vecs = embed([rec["q"] for rec in records])
    summary = defaultdict(lambda: {"n": 0, "hit": 0, "fired": 0, "abstain": 0, "expert_leak": 0, "base_leak": 0})
    for rec, vec in zip(records, vecs):
        sims = {name: float((key @ vec).max()) for name, key in keys.items()}
        decision = route_decision(rec["q"], entities, sims, 0.6, memory)
        fired = bool(decision["fired"])
        if rec.get("unstored"):
            key_name = rec["category"] + "_unstored"
        elif rec.get("compare"):
            key_name = "two_compare"
        else:
            key_name = rec["category"]
        bucket = summary[key_name]
        bucket["n"] += 1
        bucket["fired"] += int(fired)
        bucket["abstain"] += int(not fired)
        if fired:
            bucket["hit"] += int(rec["before_hit"])
            bucket["expert_leak"] += int(rec["before_leak"])
        else:
            bucket["hit"] += int(rec["base_hit"])
            bucket["base_leak"] += int(rec["base_leak"])
        if "创始人是哪一位" in rec["q"] and key_name == "title":
            sub = summary["title_founder"]
            sub["n"] += 1
            sub["fired"] += int(fired)
            sub["abstain"] += int(not fired)
            sub["hit"] += int(rec["before_hit"] if fired else rec["base_hit"])
    return summary


def cmmlu_activations(entities, keys, memory, cmmlu_dir: Path) -> dict:
    import csv

    names = sorted({name for group in entities.values() for name in group}, key=len, reverse=True)
    stems = []
    for path in sorted(cmmlu_dir.glob("*.csv")):
        with path.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if row.get("Answer") in "ABCD" and row.get("Question"):
                    stems.append(row["Question"])
    hit_stems = [text for text in stems if any(name and name in text for name in names)]
    fired = 0
    if hit_stems:
        vecs = embed(hit_stems)
        for text, vec in zip(hit_stems, vecs):
            sims = {name: float((key @ vec).max()) for name, key in keys.items()}
            if route_decision(text, entities, sims, 0.6, memory)["fired"]:
                fired += 1
    return {"n": len(stems), "name_overlap": len(hit_stems), "fired": fired}


def latency(memory: FactMemory, pairs: list[tuple[str, str]]) -> None:
    memory.rerank_calls = 0
    started = time.perf_counter()
    memory.decide_many(pairs)
    elapsed = time.perf_counter() - started
    print(
        f"  批量 {len(pairs)} 条 {elapsed:.1f}s ({1000 * elapsed / max(len(pairs), 1):.2f} ms/条) "
        f"进交叉编码器 {memory.rerank_calls}",
        flush=True,
    )
    probes = [pairs[0]]
    founder = next(((q, e) for q, e in pairs if "创始人是哪一位" in q), None)
    if founder:
        probes.append(founder)
    repeats = 15
    for sample in probes:
        memory.rerank_calls = 0
        started = time.perf_counter()
        for _ in range(repeats):
            memory.allows(*sample)
        ms = 1000 * (time.perf_counter() - started) / repeats
        print(f"  单条 {ms:.1f} ms 进交叉编码器 {memory.rerank_calls}/{repeats} {sample[0][:24]}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, default=RAW_PARA)
    parser.add_argument("--tune", type=Path, default=TUNE_JSON)
    parser.add_argument("--generate", type=Path, default=GEN_JSON)
    parser.add_argument("--cmmlu-dir", type=Path, default=Path("/tmp/cmmlu/test"))
    parser.add_argument("--filter-only", action="store_true")
    parser.add_argument("--para-mode", choices=("rel", "abs"), default="rel")
    args = parser.parse_args()

    torch.set_num_threads(4)
    frozen = freeze_reranker(args.tune)
    facts = load_facts(ROOT / "data")
    facts_by_entity = {fact["entity"]: fact for fact in facts}
    base_records = load_fact_records(ROOT / "experts")
    gate = load_fact_gate(ROOT / "experts")
    memory = FactMemory(
        base_records,
        tau=float(gate["tau"]),
        mask=str(gate.get("mask", "某")),
        value_mask=str(gate.get("value_mask", "某值")),
        use_paraphrases=False,
    )
    reranker = FactReranker(
        ROOT / "models" / "bge-reranker-base",
        cut=float(frozen["cut"]),
        delta=float(frozen["delta"]),
        passage=str(frozen["passage"]),
    )

    raw_rows = load_raw(args.raw)
    blocked = heldout_norms()
    open_facts = [json.loads(line) for line in (ROOT / "data_heldout" / "open_domain.jsonl").open(encoding="utf-8") if line.strip()]
    allowed = {}
    for rec in base_records:
        allowed[rec["entity"]] = rec["statement"] + "\n" + "\n".join(rec.get("questions") or [])
    for fact in open_facts:
        allowed[fact["entity"]] = fact["statement"] + "\n" + "\n".join(qa["q"] for qa in fact["qa"])
    cleaned, leak_stats = apply_leak_filter(raw_rows, blocked, allowed)
    print(
        f"留出题过滤: 看到 {leak_stats['seen']} 句,留下 {leak_stats['kept_leak']}, "
        f"完全相同 {leak_stats['exact']}, 包了一层 {leak_stats['wrap']}, 编辑距离≤3 {leak_stats['edit3']}, "
        f"新的拉丁词 {leak_stats['latin']}, 格式丢掉 {leak_stats['format']}",
        flush=True,
    )
    for line in leak_stats["examples"]:
        print(f"  丢掉 {line}", flush=True)

    record_by_entity = {rec["entity"]: rec for rec in base_records}
    open_records = [{
        "entity": fact["entity"],
        "value": fact["value"],
        "statement": fact["statement"],
        "questions": [qa["q"] for qa in fact["qa"]],
    } for fact in open_facts]
    prepared = []
    for row in cleaned:
        if row["entity"] in record_by_entity:
            source = record_by_entity[row["entity"]]
        else:
            source = next(rec for rec in open_records if rec["entity"] == row["entity"])
        prepared.append({
            **row,
            "statement_masked": _masked_statement(memory, source),
            "value": source.get("value", ""),
            "statement": source["statement"],
        })
    by_entity = drop_tune_thieves(memory, assign_group_paraphrases(prepared), prepared)
    attr_of = {entity: fact["attr"] for entity, fact in facts_by_entity.items()}
    for fact in open_facts:
        attr_of[fact["entity"]] = fact["attr"]
    coverage = defaultdict(int)
    founder_cov = defaultdict(int)
    for entity, questions in by_entity.items():
        attr = attr_of.get(entity, "?")
        coverage[attr] += len(questions)
        if any("创始人" in question for question in questions):
            founder_cov[attr] += 1
    print("A 的改写按掩码陈述句归组,冲突时留给生成次数多的那组。", flush=True)
    for attr, count in sorted(founder_cov.items()):
        print(f"  带「创始人」问句的实体 {attr} {count}", flush=True)
    print(
        "  平均每条 "
        + ", ".join(f"{attr}:{coverage[attr] / max(sum(1 for e in by_entity if attr_of.get(e)==attr),1):.1f}" for attr in sorted(coverage)),
        flush=True,
    )
    Path("/tmp/para_assigned.json").write_text(json.dumps(by_entity, ensure_ascii=False), encoding="utf-8")
    if args.filter_only:
        return
    open_by_entity = {entity: questions for entity, questions in by_entity.items() if entity not in record_by_entity}
    by_entity = {entity: questions for entity, questions in by_entity.items() if entity in record_by_entity}

    rows = regression_rows(facts) + load_rows(DATA_PATH)
    pairs, labels = collect_pairs(rows, facts)
    mem_none = memory
    mem_a = FactMemory(
        attach_paraphrases(base_records, by_entity),
        tau=memory.tau,
        use_paraphrases=True,
    )
    mem_b = FactMemory(base_records, tau=memory.tau, use_paraphrases=False)
    mem_b.reranker = reranker
    mem_ab = FactMemory(
        attach_paraphrases(base_records, by_entity),
        tau=memory.tau,
        use_paraphrases=True,
    )
    mem_ab.reranker = reranker

    variants = (("none", mem_none), ("A", mem_a), ("B", mem_b), ("A+B", mem_ab))
    for name, mem in variants:
        mem.rerank_calls = 0
        decided = mem.decide_many(pairs)
        print(f"  全量进交叉编码器 {mem.rerank_calls}/{len(pairs)}", flush=True)
        summarize_decisions(name, labels, decided)
        print("  耗时", flush=True)
        latency(mem, pairs[:400])

    open_plain = open_records
    open_with = attach_paraphrases(open_records, open_by_entity)
    print("\n== 开放域 ==", flush=True)
    train_of = {"none": mem_none, "A": mem_a, "B": mem_b, "A+B": mem_ab}
    for name, extra, use_para, use_rank in (
        ("none", open_plain, False, False),
        ("A", open_with, True, False),
        ("B", open_plain, False, True),
        ("A+B", open_with, True, True),
    ):
        bank = base_records + extra
        # A 的已存事实也带着改写,和主评测同一套。
        if use_para:
            bank = attach_paraphrases(base_records, by_entity) + extra
        mem = FactMemory(bank, tau=memory.tau, use_paraphrases=use_para)
        if use_rank:
            mem.reranker = reranker
        counts = open_domain_counts(mem, train_of[name], facts, open_facts)
        print(
            f"  {name}: 在库留出问法 {counts['open_pos'][0]}/{counts['open_pos'][1]} "
            f"问错事实弃权 {counts['open_neg'][0]}/{counts['open_neg'][1]} "
            f"未见关系弃权 {counts['unseen'][0]}/{counts['unseen'][1]}",
            flush=True,
        )

    print("\n== 同一批 50 条生成(复用已有回答,只改挂载) ==", flush=True)
    generated = json.loads(args.generate.read_text(encoding="utf-8"))["records"]
    entries, entities = load_expert_entities(ROOT / "experts")
    keys = {entry["expert"]: torch.load(_norm_key(entry["key_path"]), weights_only=True) for entry in entries}
    for name, mem in variants:
        summary = generation_counts(generated, entities, keys, mem)
        print(f"  {name}", flush=True)
        for key in (
            "canonical", "org_suffix", "title", "title_founder", "colloquial", "long_context", "two_entity",
            "org_suffix_unstored", "title_unstored", "colloquial_unstored", "long_context_unstored", "two_entity_unstored",
            "two_compare", "general",
        ):
            bucket = summary.get(key)
            if not bucket or not bucket["n"]:
                continue
            print(
                f"    {key:24s} n={bucket['n']:3d} hit={bucket['hit']:3d} fired={bucket['fired']:3d} "
                f"abstain={bucket['abstain']:3d} expert_leak={bucket['expert_leak']:3d} base_leak={bucket['base_leak']:3d}",
                flush=True,
            )

    if args.cmmlu_dir.exists():
        print("\n== CMMLU ==", flush=True)
        for name, mem in variants:
            report = cmmlu_activations(entities, keys, mem, args.cmmlu_dir)
            print(
                f"  {name}: n={report['n']} 题干里出现在册名字 {report['name_overlap']} 激活 {report['fired']}",
                flush=True,
            )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""给巩固训练集打分:原问、留出的复述、从没写过的问题是否弃权。

生成用训练程序的贪心解码。弃权用和手机路由一样的规则:
问句里没有这四家实体时,bge 和专家键的最高余弦低于 0.6 就不挂专家。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from router import embed  # noqa: E402


def hit(answer: str, gold: str) -> bool:
    needle = gold.rstrip("年")
    return needle in answer


def main() -> int:
    bench = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    gen_path = Path(sys.argv[2])
    tok_dir = Path(sys.argv[3])
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(tok_dir)
    decoded = []
    for line in gen_path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("[gen_line]"):
            continue
        new = line.split("new=", 1)[1].strip()
        ids = [] if not new else [int(part) for part in new.split(",") if part]
        # 遇到 im_end 就停。
        if 151645 in ids:
            ids = ids[: ids.index(151645)]
        decoded.append(tok.decode(ids, skip_special_tokens=True).strip())
    facts = bench["facts"]
    held = bench["held_out"]
    never = bench["never_written"]
    primary = [fact["qa"][0] for fact in facts]
    expect = len(primary) + len(held)
    if len(decoded) < expect:
        raise SystemExit(f"生成了 {len(decoded)} 行,需要 {expect}")
    primary_rows = []
    ok = 0
    for fact, answer in zip(facts, decoded[: len(facts)]):
        good = hit(answer, fact["value"])
        ok += int(good)
        primary_rows.append({"q": fact["qa"][0]["q"], "gold": fact["value"], "answer": answer, "hit": good})
    held_rows = []
    held_ok = 0
    for row, answer in zip(held, decoded[len(facts):]):
        good = hit(answer, row["a"])
        held_ok += int(good)
        held_rows.append({"q": row["q"], "gold": row["a"], "answer": answer, "hit": good})
    keys = []
    for fact in facts:
        keys.append(fact["statement"])
        keys.extend(qa["q"] for qa in fact["qa"])
    queries = list(never)
    vectors = embed(queries + keys)
    qv = vectors[: len(queries)]
    kv = vectors[len(queries):]
    sims = (qv @ kv.T).max(dim=1).values.tolist()
    entities = [fact["entity"] for fact in facts]
    abstain_rows = []
    abstain_ok = 0
    for question, sim in zip(queries, sims):
        named = any(entity and entity in question for entity in entities)
        abstained = (not named) and sim < 0.6
        abstain_ok += int(abstained)
        abstain_rows.append({"q": question, "max_sim": round(float(sim), 4), "named_entity": named, "abstained": abstained})
    report = {
        "primary": f"{ok}/{len(primary_rows)}",
        "held_out_paraphrase": f"{held_ok}/{len(held_rows)}",
        "never_written_abstain": f"{abstain_ok}/{len(abstain_rows)}",
        "primary_rows": primary_rows,
        "held_out_rows": held_rows,
        "abstain_rows": abstain_rows,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

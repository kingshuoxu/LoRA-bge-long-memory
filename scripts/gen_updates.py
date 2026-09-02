"""矛盾更新数据生成器:从已入库的事实中抽样,生成"同实体新值"的更新流(冲突压力测试用)。

产出(--out 目录,默认 data_updates/):
- updates.jsonl:50 条更新(每批 10 条,seed 固定),含 old_value 供残留检查;
- batch_{k}.jsonl:完整评测集——更新过的 10 条用新值,其余 40 条保持原值;
- generic_questions.jsonl:原样复制(选择性测试用)。

用法: python scripts/gen_updates.py [--per-batch 10] [--seed 7]
"""
import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gen_data import ATTRS, GENERIC_QUESTIONS, make_value  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=Path("data"))
    ap.add_argument("--out", type=Path, default=Path("data_updates"))
    ap.add_argument("--batches", type=int, default=5)
    ap.add_argument("--per-batch", type=int, default=10)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    all_updates = []
    for b in range(args.batches):
        facts = [json.loads(l) for l in (args.data / f"batch_{b}.jsonl").open(encoding="utf-8")]
        idx = rng.sample(range(len(facts)), args.per_batch)
        picked = set(idx)
        updates = []
        for i in idx:
            f = facts[i]
            spec = ATTRS[f["attr"]]
            # 新值必须不同于旧值,且不与同批其他值撞车
            used = {g["value"] for g in facts}
            v = make_value(rng, spec["value_kind"], used - {f["value"]})
            distractors = [c for c in f["mc"]["choices"] if c != f["value"]][:3]
            choices = distractors + [v]
            rng.shuffle(choices)
            updates.append({
                "id": f["id"], "entity": f["entity"], "attr": f["attr"],
                "old_value": f["value"], "value": v,
                "statement": spec["statement"].format(e=f["entity"], v=v),
                "qa": [{"q": q.format(e=f["entity"]), "a": v} for q in spec["questions"]],
                "mc": {"q": f["mc"]["q"], "choices": choices, "answer_idx": choices.index(v)},
            })
        # 完整评测集:被更新的条目整条替换为新版
        eval_facts = [next(u for u in updates if u["id"] == f["id"]) if i in picked else f
                      for i, f in enumerate(facts)]
        with (args.out / f"batch_{b}.jsonl").open("w", encoding="utf-8") as fo:
            for f in eval_facts:
                fo.write(json.dumps(f, ensure_ascii=False) + "\n")
        for u in updates:
            u["batch"] = b  # 仅用于核对;update_expert 必须自己路由定位,不许读这个字段
            all_updates.append(u)
        print(f"批次 {b}: {len(updates)} 条更新,评测集 {len(eval_facts)} 条")

    with (args.out / "updates.jsonl").open("w", encoding="utf-8") as fo:
        for u in all_updates:
            fo.write(json.dumps(u, ensure_ascii=False) + "\n")

    gq = args.out / "generic_questions.jsonl"
    with gq.open("w", encoding="utf-8") as fo:
        for q, a in GENERIC_QUESTIONS:
            fo.write(json.dumps({"q": q, "a": a}, ensure_ascii=False) + "\n")
    print(f"\n共 {len(all_updates)} 条更新 → {args.out}/updates.jsonl")
    sample = json.loads((args.out / "updates.jsonl").open(encoding="utf-8").readline())
    print("样例:", json.dumps(sample, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

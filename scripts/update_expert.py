"""记忆更新:同实体新值 → 定位旧专家 → 重训该专家 → 覆盖 adapter 与路由键(冲突压力测试)。

定位机制(§14 的教训:语义向量对"改值"过度敏感,新陈述句与旧键 sim 仅 0.81~0.96,
与跨事实 0.921 大量重叠,不能用作同事实判定):
1. 主路:实体字符串匹配——train_expert 保存的 key_texts.json 里找包含该实体的专家,
   唯一命中即定位(虚构实体名全局唯一);
2. 兜底:无 key_texts 或实体不唯一时,退回 bge max-sim + τ_dedup(0.94)。

流程:逐条定位 → 按专家分组 → 新值应用到该专家源数据集的工作副本 →
调 train_expert.py 重训该专家,覆盖保存 adapter 与路由键(其内部对 router.jsonl 按 batch 去重)。

注意:
- 直接在 --experts 目录上覆盖训练;生产用法请先备份(本实验对 experts_stress 副本操作);
- updates.jsonl 里的 batch/old_value 字段只用于核对,定位本身不读;
- 未定位的更新跳过并报告——它们若当新事实写入会造成同实体双专家。

用法: python scripts/update_expert.py --updates data_updates/updates.jsonl --experts experts_stress --rocm
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).parent))
from router import embed  # noqa: E402

FACT_KEYS = ("id", "entity", "attr", "value", "statement", "qa", "mc")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--updates", type=Path, required=True, help="更新流 jsonl(同实体新值)")
    ap.add_argument("--experts", type=Path, default=Path("experts_stress"))
    ap.add_argument("--data", type=Path, default=Path("data"), help="原始批次数据目录(各专家数据集底稿)")
    ap.add_argument("--work", type=Path, default=Path(".cache/update_work"), help="更新后数据集的工作目录")
    ap.add_argument("--tau-dedup", type=float, default=0.94, help="同事实更新判定阈值(§9.2)")
    ap.add_argument("--rank", type=int, default=32)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--bsz", type=int, default=16)
    ap.add_argument("--model", default="models/Qwen2.5-0.5B-Instruct")
    ap.add_argument("--rocm", action="store_true")
    ap.add_argument("--cpu", action="store_true")
    ap.add_argument("--report", type=Path, default=None, help="逐条定位报告 jsonl")
    args = ap.parse_args()

    updates = [json.loads(l) for l in args.updates.open(encoding="utf-8")]
    entries = [json.loads(l) for l in (args.experts / "router.jsonl").open(encoding="utf-8")]
    keys = {e["expert"]: torch.load(e["key_path"], weights_only=True) for e in entries}
    batch_of = {e["expert"]: e["batch"] for e in entries}

    # 1) 逐条定位:主路实体匹配,兜底 bge max-sim + τ_dedup
    # 实体匹配两级:key_texts 子串粗筛(短实体名可能是长实体名的子串)→ 数据集字段精确匹配裁决
    key_texts = {}
    for e in entries:
        p = Path(e["key_path"]).parent / "key_texts.json"
        key_texts[e["expert"]] = json.load(p.open(encoding="utf-8")) if p.exists() else None
    facts_cache: dict[int, list] = {}

    def exact_hit(expert: str, entity: str) -> bool:
        b = batch_of[expert]
        if b not in facts_cache:
            facts_cache[b] = [json.loads(l) for l in (args.data / f"batch_{b}.jsonl").open(encoding="utf-8")]
        return any(f["entity"] == entity for f in facts_cache[b])

    located, missed = [], []
    need_vec = []
    for u in updates:
        cands = [n for n, ts in key_texts.items() if ts and any(u["entity"] in t for t in ts)]
        exact = [n for n in cands if exact_hit(n, u["entity"])]
        if len(exact) == 1:
            located.append((u, exact[0], 1.0, "entity"))
        else:
            need_vec.append((u, exact or cands))
    if need_vec:
        qs = embed([u["statement"] for u, _ in need_vec])
        for (u, cands), qv in zip(need_vec, qs):
            best, s = max(((n, (k @ qv).max().item()) for n, k in keys.items()), key=lambda kv: kv[1])
            if s >= args.tau_dedup:
                located.append((u, best, s, "vector"))
            else:
                missed.append((u, best, s, f"entity_cands={len(cands)}"))
    print(f"定位: {len(located)}/{len(updates)} 条(实体 {sum(1 for *_, m in located if m == 'entity')},"
          f"向量 {sum(1 for *_, m in located if m == 'vector')});未定位 {len(missed)} 条")
    for u, best, s, m in missed:
        print(f"  [未定位] {u['entity']}/{u['attr']} 最近 {best} sim={s:.3f} [{m}]"
              f"(若当新事实写入会造成同实体双专家,已跳过)")
    # 2) 按专家分组,新值应用到工作副本
    by_expert: dict[str, list] = {}
    for u, best, s, m in located:
        by_expert.setdefault(best, []).append((u, s))
    args.work.mkdir(parents=True, exist_ok=True)
    for expert, items in sorted(by_expert.items()):
        b = batch_of[expert]
        facts = [json.loads(l) for l in (args.data / f"batch_{b}.jsonl").open(encoding="utf-8")]
        applied = 0
        for u, s in items:
            for i, f in enumerate(facts):
                if f["entity"] == u["entity"] and f["attr"] == u["attr"]:
                    assert f["value"] == u["old_value"], \
                        f"旧值不符: {f['id']} 数据里={f['value']},更新流old_value={u['old_value']}"
                    facts[i] = {k: u[k] for k in FACT_KEYS}
                    applied += 1
                    break
            else:
                print(f"  [错配] {u['entity']}/{u['attr']} 在 {expert}(batch {b}) 数据集里找不到对应事实")
        with (args.work / f"batch_{b}.jsonl").open("w", encoding="utf-8") as fo:
            for f in facts:
                fo.write(json.dumps(f, ensure_ascii=False) + "\n")
        print(f"{expert}(batch {b}): 应用 {applied}/{len(items)} 条更新")

    # 3) 逐专家重训(覆盖 --experts 下对应 adapter 与路由键)
    for expert in sorted(by_expert):
        b = batch_of[expert]
        cmd = [sys.executable, str(Path(__file__).parent / "train_expert.py"),
               "--batch", str(b), "--data", str(args.work), "--out", str(args.experts),
               "--rank", str(args.rank), "--lr", str(args.lr),
               "--epochs", str(args.epochs), "--bsz", str(args.bsz), "--model", args.model,
               "--rocm" if args.rocm else "--cpu"]
        print(f"\n=== 重训 {expert}(batch {b})", flush=True)
        r = subprocess.run(cmd)
        if r.returncode != 0:
            print(f"!! {expert} 重训失败(exit {r.returncode}),该专家保持更新前状态")

    # 4) 报告
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("w", encoding="utf-8") as fo:
            for u, best, s, m in located + missed:
                fo.write(json.dumps({
                    "id": u["id"], "entity": u["entity"], "attr": u["attr"],
                    "old_value": u["old_value"], "value": u["value"],
                    "expert": best, "sim": round(s, 4), "method": m,
                    "located": (u, best, s, m) in located,
                    "batch_truth": u.get("batch"),
                }, ensure_ascii=False) + "\n")
        print(f"\n报告: {args.report}")


if __name__ == "__main__":
    main()

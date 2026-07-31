"""路由扩展性压测:专家数 E 增大时,bge 检索式路由还能分对家吗?

只测路由,不生成答案:路由键 = 事实文本的 bge 向量(与 train_expert 建键逻辑一致),
与 LoRA 权重无关,因此无需真训 E 个专家。

扫描 E ∈ {5,10,25,50}(data_router/ 前 E 批),指标:
- top-1 路由准确率:每条事实的 3 种问法分别编码,argmax 专家是否 = 自家;
- 路由边际:自家最高 sim 与最强别家 sim 之差的分布(min/中位);
- 常识误激活:20 条常识问题在各 E 下 max-sim ≥ τ 的比例(τ=0.5)。

用法: python scripts/router_scale.py [--n-batches 50] [--es 5,10,25,50] [--n-qa 3]
"""
import argparse
import json
import sys
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).parent))
from router import embed

TAU = 0.5
DATA = Path("data_router")


def load_batch(k):
    return [json.loads(l) for l in open(DATA / f"batch_{k}.jsonl", encoding="utf-8")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-batches", type=int, default=50)
    ap.add_argument("--es", default="5,10,25,50")
    ap.add_argument("--n-qa", type=int, default=3, help="每条事实取几种问法做查询(1=只 qa[0],省时)")
    args = ap.parse_args()
    ES = [int(x) for x in args.es.split(",")]
    n_experts = max(ES)
    batches = [load_batch(k) for k in range(n_experts)]

    # 建键:与 train_expert 一致(陈述句 + 3 问句,每条事实 4 向量)
    print("建键与编码查询(bge, CPU)...", flush=True)
    keys, queries = [], []  # keys: (E, n_texts, dim); queries: (E, n_facts*n_qa, dim)
    for k, facts in enumerate(batches):
        key_texts, q_texts = [], []
        for f in facts:
            key_texts.append(f["statement"])
            key_texts.extend(qa["q"] for qa in f["qa"])
            q_texts.extend(qa["q"] for qa in f["qa"][:args.n_qa])
        keys.append(embed(key_texts))
        queries.append((k, embed(q_texts)))
        if k % 20 == 19:
            print(f"  {k + 1}/{n_experts} 批完成", flush=True)
    generic = embed([json.loads(l)["q"] for l in open(DATA / "generic_questions.jsonl", encoding="utf-8")])

    print(f"\n{'E':>4} | {'top-1 路由准确率':>14} | {'边际 min':>8} | {'边际中位':>8} | {'常识误激活':>9}")
    print("-" * 60)
    for E in ES:
        K = torch.cat(keys[:E])  # (E*n_texts, dim)
        # 每个向量所属专家 id,用于 argmax 归家
        owner = torch.cat([torch.full((kmat.shape[0],), i, dtype=torch.long)
                           for i, kmat in enumerate(keys[:E])])
        correct = total = 0
        margins = []
        for k, q in queries[:E]:
            sims = q @ K.T  # (n_q, E*n_texts)
            best_sim, best_idx = sims.max(dim=1)
            correct += (owner[best_idx] == k).sum().item()
            total += q.shape[0]
            # 边际:从别家键中取最强者
            own_mask = owner == k
            other_sims = sims.masked_fill(own_mask, -1).max(dim=1).values
            margins.append(best_sim - other_sims)
        m = torch.cat(margins)
        gsim = (generic @ K.T).max(dim=1).values
        false_fire = (gsim >= TAU).float().mean().item()
        print(f"{E:>4} | {correct / total:>13.1%} | {m.min():>8.3f} | {m.median():>8.3f} | {false_fire:>8.0%}")


if __name__ == "__main__":
    main()

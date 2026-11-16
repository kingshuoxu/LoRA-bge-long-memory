#!/usr/bin/env python3
"""对照 PyTorch mean-pooling 和 llama-embedding 的 bge 向量。

余弦按条计算。路由对照把 llama 问句向量送进 memory-route,和 router.py 的决定比。
键和事实向量仍用 PyTorch 导出的那份,和手机上 adb push 的索引相同。
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "android" / "scripts"))

from router import embed, load_fact_memory, load_router, route_decision  # noqa: E402
from verify_router import collect_questions, entities_of  # noqa: E402

EMB = ROOT / "android" / "out" / "qvac-b7349" / "build" / "bin" / "llama-embedding"
GGUF = ROOT / "android" / "out" / "gguf" / "bge-small-zh-v1.5-f16.gguf"
BIN = ROOT / "android" / "router" / "memory-route"


def llama_embed(texts: list[str], work: Path) -> np.ndarray:
    prompts = work / "prompts.txt"
    # 一行一条。文本里没有换行;有的话换成空格,避免 -f 把一条拆开。
    prompts.write_text("".join(t.replace("\n", " ") + "\n" for t in texts), encoding="utf-8")
    proc = subprocess.run(
        [str(EMB), "-m", str(GGUF), "-f", str(prompts),
         "--pooling", "mean", "--embd-normalize", "2",
         "-c", "128", "-ngl", "0", "--embd-output-format", "array"],
        check=True, capture_output=True, text=True,
    )
    raw = proc.stdout.strip()
    if not raw.startswith("["):
        raise SystemExit(f"llama-embedding 没有打出数组:\n{raw[:200]}\n{proc.stderr[-400:]}")
    arr = np.asarray(json.loads(raw), dtype=np.float32)
    if arr.shape != (len(texts), 512):
        raise SystemExit(f"向量形状 {arr.shape}, 期望 {(len(texts), 512)}")
    return arr


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="问句最多取多少条,0 为全部")
    ap.add_argument("--route", action="store_true", help="用 llama 问句向量跑 C++ 路由并对照 Python")
    ap.add_argument("--min-cosine", type=float, default=0.999)
    args = ap.parse_args()
    work = ROOT / "android" / "out" / "bge-check"
    work.mkdir(parents=True, exist_ok=True)
    questions = collect_questions(ROOT / "experts")
    if args.limit:
        questions = questions[:args.limit]
    entities = entities_of(ROOT / "experts")
    memory = load_fact_memory(ROOT / "experts")
    import torch
    keys = {}
    for entry in load_router(ROOT / "experts" / "router.jsonl"):
        keys[entry["expert"]] = torch.load(entry["key_path"], weights_only=True)
    texts = [row["q"] for row in questions]
    masked = [memory.mask_query(q) for q in texts]
    extra = list(memory._texts)
    for entry in load_router(ROOT / "experts" / "router.jsonl"):
        extra.extend(json.loads((Path(entry["key_path"]).parent / "key_texts.json").read_text(encoding="utf-8")))
    unique = list(dict.fromkeys(texts + masked + extra))
    print(f"问句 {len(questions)}, 去重文本 {len(unique)}", flush=True)
    print("PyTorch 编码...", flush=True)
    pt = embed(unique).numpy()
    print("llama-embedding 编码...", flush=True)
    ll = llama_embed(unique, work)
    cos = (pt * ll).sum(axis=1)
    # 两边都做过 L2。再归一化一次,避免数值误差把余弦抬过 1。
    pt_n = pt / np.clip(np.linalg.norm(pt, axis=1, keepdims=True), 1e-9, None)
    ll_n = ll / np.clip(np.linalg.norm(ll, axis=1, keepdims=True), 1e-9, None)
    cos = (pt_n * ll_n).sum(axis=1)
    order = np.argsort(cos)
    upper = np.array([any("A" <= ch <= "Z" for ch in t) for t in unique])
    print(f"余弦 min={cos.min():.6f} mean={cos.mean():.6f} p01={np.quantile(cos, 0.01):.6f}")
    if (~upper).any():
        print(f"无大写字母 min={cos[~upper].min():.6f} mean={cos[~upper].mean():.6f} n={int((~upper).sum())}")
    if upper.any():
        print(f"含大写字母 min={cos[upper].min():.6f} mean={cos[upper].mean():.6f} n={int(upper.sum())}")
    for i in order[:5]:
        print(f"  {cos[i]:.6f} {unique[i][:60]}")
    # llama.cpp 的 WordPiece 会把拉丁字母折成小写,而 bge-small-zh 的 BertTokenizer 不折。
    # 没有大写字母的句子应当贴住 1。含 CEO 这类大写的句子单独记,路由对照在后面。
    cosine_gap = float(cos[~upper].min()) < args.min_cosine if (~upper).any() else True
    if not args.route:
        return
    by_text = {t: i for i, t in enumerate(unique)}
    qv = ll[[by_text[t] for t in texts]]
    mv = ll[[by_text[t] for t in masked]]
    # 键和事实用 PyTorch,问句用 llama。这是手机上的组合。
    index_dir = work / "index"
    index_dir.mkdir(exist_ok=True)
    experts_json = []
    for name, ents in entities.items():
        key = keys[name].contiguous().float().numpy()
        (index_dir / f"{name}.f32").write_bytes(key.tobytes())
        experts_json.append({"name": name, "entities": ents, "n_keys": int(key.shape[0]), "keys": f"{name}.f32"})
    fact_rows = [{"entity": memory._owners[i], "text": memory._texts[i]} for i in range(len(memory._texts))]
    (index_dir / "facts.f32").write_bytes(memory._vec.contiguous().float().numpy().tobytes())
    (index_dir / "index.json").write_text(json.dumps({
        "tau": 0.6, "dim": 512, "experts": experts_json,
        "facts": {"tau": memory.tau, "mask": memory.mask, "vectors": "facts.f32", "rows": fact_rows},
    }, ensure_ascii=False), encoding="utf-8")
    (index_dir / "q.f32").write_bytes(qv.astype(np.float32).tobytes())
    (index_dir / "mq.f32").write_bytes(mv.astype(np.float32).tobytes())
    qpath = index_dir / "queries.jsonl"
    with qpath.open("w", encoding="utf-8") as f:
        for i, row in enumerate(questions):
            f.write(json.dumps({"id": row["id"], "q": row["q"], "q_row": i, "mq_row": i}, ensure_ascii=False) + "\n")
    outp = index_dir / "out.jsonl"
    subprocess.run([str(BIN), "decide", "--index", str(index_dir / "index.json"),
                    "--queries", str(qpath), "--out", str(outp),
                    "--q-vectors", str(index_dir / "q.f32"),
                    "--mq-vectors", str(index_dir / "mq.f32")], check=True)
    got = {row["id"]: row for row in (json.loads(line) for line in outp.read_text(encoding="utf-8").splitlines() if line.strip())}
    pt_q = pt[[by_text[t] for t in texts]]
    bad = 0
    shown = 0
    for i, row in enumerate(questions):
        q = torch.from_numpy(pt_q[i])
        sims = {name: float((keys[name] @ q).max()) for name in entities}
        decision = route_decision(row["q"], entities, sims, 0.6, memory)
        cpp = got[row["id"]]
        if decision["expert"] != cpp["expert"] or bool(decision["fired"]) != bool(cpp["fired"]) or decision["reason"] != cpp["reason"]:
            bad += 1
            if shown < 8:
                shown += 1
                print(f"  路由不一致 {row['id']} {row['q'][:40]}")
                print(f"    py { {k: decision[k] for k in ('expert','fired','reason','sim')} }")
                print(f"    llama问句 {cpp}")
    print(f"llama 问句 + PyTorch 键: {len(questions) - bad}/{len(questions)} 与 Python 一致")
    if cosine_gap:
        raise SystemExit("没有大写字母的句子余弦低于阈值")
    if bad:
        raise SystemExit(f"路由不一致 {bad}")


if __name__ == "__main__":
    main()

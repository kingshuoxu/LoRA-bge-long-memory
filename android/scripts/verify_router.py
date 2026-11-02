#!/usr/bin/env python3
"""对照 scripts/router.py 和 android/router/memory-route 的路由决定。

默认只比字符串逻辑(不加载 bge)。--full 再把事实闸和真实向量算进去。
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from eval_entity_guard_realistic import load_facts, load_rows, regression_rows  # noqa: E402
from router import (  # noqa: E402
    extract_entities_from_key_texts,
    load_fact_memory,
    load_router,
    route_decision,
)

BIN = ROOT / "android" / "router" / "memory-route"
DATA_GUARD = ROOT / "data_guard" / "realistic_queries.jsonl"


def entities_of(experts: Path) -> dict[str, list[str]]:
    out = {}
    for entry in load_router(experts / "router.jsonl"):
        texts = json.loads((Path(entry["key_path"]).parent / "key_texts.json").read_text(encoding="utf-8"))
        out[entry["expert"]] = extract_entities_from_key_texts(texts)
    return out


def write_index(path: Path, entities: dict[str, list[str]], tau: float = 0.6) -> None:
    path.write_text(json.dumps({
        "tau": tau,
        "dim": 0,
        "experts": [{"name": name, "entities": ents, "n_keys": 0} for name, ents in entities.items()],
    }, ensure_ascii=False), encoding="utf-8")


def collect_questions(experts: Path) -> list[dict]:
    facts = load_facts(ROOT / "data")
    rows = []
    for row in regression_rows(facts):
        rows.append({"id": row["id"], "q": row["q"]})
    for row in load_rows(DATA_GUARD):
        rows.append({"id": row["id"], "q": row["q"]})
    for b in range(5):
        for line in (ROOT / "data" / f"batch_{b}.jsonl").open(encoding="utf-8"):
            fact = json.loads(line)
            for i, qa in enumerate(fact["qa"]):
                rows.append({"id": f"batch{b}-{fact['id']}-{i}", "q": qa["q"]})
    for i, line in enumerate((ROOT / "data" / "generic_questions.jsonl").open(encoding="utf-8")):
        item = json.loads(line)
        q = item["q"] if isinstance(item, dict) else item
        rows.append({"id": f"generic-{i}", "q": q})
    held = ROOT / "data_heldout" / "open_domain.jsonl"
    if held.exists():
        for line in held.open(encoding="utf-8"):
            fact = json.loads(line)
            for i, qa in enumerate(fact.get("qa") or []):
                rows.append({"id": f"open-{fact['id']}-{i}", "q": qa["q"]})
    return rows


def run_cpp(index: Path, queries: Path, out: Path) -> list[dict]:
    subprocess.run([str(BIN), "decide", "--index", str(index), "--queries", str(queries),
                    "--out", str(out), "--no-fact"], check=True)
    return [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line.strip()]


def check_extract(entities: dict[str, list[str]], tmp: Path) -> None:
    for entry in load_router(ROOT / "experts" / "router.jsonl"):
        src = Path(entry["key_path"]).parent / "key_texts.json"
        got_path = tmp / f"{entry['expert']}.entities.json"
        subprocess.run([str(BIN), "extract", "--key-texts", str(src)], check=True,
                       stdout=got_path.open("w", encoding="utf-8"))
        got = json.loads(got_path.read_text(encoding="utf-8"))
        exp = entities[entry["expert"]]
        # Python 用 set,同长度名字的次序随哈希变。名单成员必须一致。
        # C++ 同长度按 key_texts 里第一次出现的顺序,导出的 index 用的是下面这份 Python 名单。
        if set(got) != set(exp) or len(got) != len(exp):
            raise SystemExit(f"实体抽取不一致 {entry['expert']}: cpp={got[:8]} py={exp[:8]}")
    print(f"实体抽取: {len(entities)} 个专家的名单成员与 Python 一致")


def compare_scenario(name: str, questions: list[dict], entities: dict[str, list[str]],
                     sims_of, tmp: Path, tau: float = 0.6) -> int:
    index = tmp / f"{name}.index.json"
    qpath = tmp / f"{name}.queries.jsonl"
    opath = tmp / f"{name}.out.jsonl"
    write_index(index, entities, tau)
    with qpath.open("w", encoding="utf-8") as f:
        for row in questions:
            sims = sims_of(entities)
            f.write(json.dumps({
                "id": row["id"], "q": row["q"], "sims": sims, "entities": entities,
            }, ensure_ascii=False) + "\n")
    got = {row["id"]: row for row in run_cpp(index, qpath, opath)}
    bad = 0
    shown = 0
    for row in questions:
        decision = route_decision(row["q"], entities, sims_of(entities), tau, None)
        cpp = got[row["id"]]
        py_expert = decision["expert"]
        fields = (
            py_expert == cpp["expert"]
            and bool(decision["fired"]) == bool(cpp["fired"])
            and decision["reason"] == cpp["reason"]
            and decision["candidate"] == cpp["candidate"]
        )
        if not fields:
            bad += 1
            if shown < 8:
                shown += 1
                print(f"  不一致 {name} {row['id']} {row['q'][:40]}")
                print(f"    py {decision}")
                print(f"    cpp {cpp}")
    print(f"{name}: {len(questions) - bad}/{len(questions)} 一致" + (f", 不一致 {bad}" if bad else ""))
    return bad


def main() -> None:
    import os
    os.chdir(ROOT)
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="加上事实闸(需要 bge)")
    ap.add_argument("--limit", type=int, default=0, help="只取前 N 条问句,0 为全部")
    args = ap.parse_args()
    if not BIN.exists():
        subprocess.run(["make", "-C", str(BIN.parent)], check=True)
    tmp = ROOT / "android" / "out" / "router-check"
    tmp.mkdir(parents=True, exist_ok=True)
    entities = entities_of(ROOT / "experts")
    check_extract(entities, tmp)
    questions = collect_questions(ROOT / "experts")
    if args.limit:
        questions = questions[:args.limit]
    print(f"问句 {len(questions)}")
    names = list(entities)
    bad = 0
    bad += compare_scenario("sim99", questions, entities, lambda ents: {n: 0.99 for n in ents}, tmp)
    bad += compare_scenario("sim0", questions, entities, lambda ents: {n: 0.0 for n in ents}, tmp)
    bad += compare_scenario(
        "ranked", questions, entities,
        lambda ents: {n: 0.99 - 0.1 * i for i, n in enumerate(ents)}, tmp)
    dropped = {n: ents for n, ents in entities.items() if n != "expert_4"}
    bad += compare_scenario("drop4", questions, dropped, lambda ents: {n: 0.99 for n in ents}, tmp)
    if bad:
        raise SystemExit(f"逻辑路由不一致 {bad} 条")
    print("逻辑路由: 全部一致")
    if not args.full:
        return
    # 事实闸:用 PyTorch 向量,C++ 只做点积和阈值。
    from router import embed
    import torch
    memory = load_fact_memory(ROOT / "experts")
    if memory is None or memory.reranker is not None:
        raise SystemExit("事实闸应存在且交叉编码器关闭")
    keys = {}
    for entry in load_router(ROOT / "experts" / "router.jsonl"):
        keys[entry["expert"]] = torch.load(entry["key_path"], weights_only=True)
    texts = [row["q"] for row in questions]
    masked = [memory.mask_query(q) for q in texts]
    # 问句和掩码后问句一起编码,避免加载两遍。
    vecs = embed(texts + masked)
    qv, mv = vecs[:len(texts)], vecs[len(texts):]
    index_dir = tmp / "full"
    index_dir.mkdir(exist_ok=True)
    experts_json = []
    for name, ents in entities.items():
        key = keys[name].contiguous().float()
        (index_dir / f"{name}.f32").write_bytes(key.numpy().tobytes())
        experts_json.append({
            "name": name, "entities": ents, "n_keys": int(key.shape[0]), "keys": f"{name}.f32",
        })
    fact_rows = [{"entity": memory._owners[i], "text": memory._texts[i]} for i in range(len(memory._texts))]
    (index_dir / "facts.f32").write_bytes(memory._vec.contiguous().float().numpy().tobytes())
    (index_dir / "index.json").write_text(json.dumps({
        "tau": 0.6,
        "dim": int(memory._vec.shape[1]),
        "experts": experts_json,
        "facts": {"tau": memory.tau, "mask": memory.mask, "vectors": "facts.f32", "rows": fact_rows},
    }, ensure_ascii=False), encoding="utf-8")
    (index_dir / "q.f32").write_bytes(qv.contiguous().float().numpy().tobytes())
    (index_dir / "mq.f32").write_bytes(mv.contiguous().float().numpy().tobytes())
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
    bad = 0
    shown = 0
    for i, row in enumerate(questions):
        q = qv[i]
        sims = {name: float((keys[name] @ q).max()) for name in entities}
        decision = route_decision(row["q"], entities, sims, 0.6, memory)
        cpp = got[row["id"]]
        if decision["expert"] != cpp["expert"] or bool(decision["fired"]) != bool(cpp["fired"]) or decision["reason"] != cpp["reason"]:
            bad += 1
            if shown < 8:
                shown += 1
                print(f"  事实闸不一致 {row['id']} {row['q'][:40]}")
                print(f"    py { {k: decision[k] for k in ('expert','fired','reason','sim')} }")
                print(f"    cpp {cpp}")
    print(f"事实闸: {len(questions) - bad}/{len(questions)} 一致")
    if bad:
        raise SystemExit(f"事实闸不一致 {bad}")


if __name__ == "__main__":
    main()

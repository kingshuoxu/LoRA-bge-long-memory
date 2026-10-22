"""用和 scripts/eval_memory.py 相同的路由与打分，在 CPU 上以 float32 重跑五个研究专家。

官方脚本把权重写成 float16。CPU 上 Half 的矩阵乘不可用，所以这里保持它的
answer()、τ=0.6 和实体守卫，只把 dtype 换成 float32。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

from eval_memory import answer
from router import embed, extract_entities_from_key_texts, verify_entity_guard


def main():
    device = torch.device("cpu")
    torch.set_num_threads(torch.get_num_threads())
    model_path = ROOT / "models" / "Qwen2.5-0.5B-Instruct"
    tok = AutoTokenizer.from_pretrained(model_path)
    base = AutoModelForCausalLM.from_pretrained(model_path, torch_dtype=torch.float32).to(device)
    experts = ROOT / "experts"
    router_rows = [json.loads(line) for line in (experts / "router.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    first = router_rows[0]
    model = PeftModel.from_pretrained(base, experts / first["expert"], adapter_name=first["expert"])
    for row in router_rows[1:]:
        model.load_adapter(experts / row["expert"], adapter_name=row["expert"])
    model.eval()
    keys = {}
    entities = {}
    for row in router_rows:
        key_path = Path(str(row["key_path"]).replace("\\", "/"))
        if not key_path.is_file():
            key_path = experts / row["expert"] / "router_key.pt"
        keys[row["expert"]] = torch.load(key_path, weights_only=True)
        texts = json.loads((key_path.parent / "key_texts.json").read_text(encoding="utf-8"))
        entities[row["expert"]] = extract_entities_from_key_texts(texts)

    def route_query(text: str):
        query = embed([text])[0]
        sims = {name: float((key @ query).max().item()) for name, key in keys.items()}
        best, sim = max(sims.items(), key=lambda item: item[1])
        entity_pass = verify_entity_guard(text, entities.get(best, []))
        return best, sim, sim >= 0.6 and entity_pass

    generic = [json.loads(line) for line in (ROOT / "data" / "generic_questions.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    false_fire = 0
    for index, item in enumerate(generic, start=1):
        question = item["q"]
        _best, _sim, fired = route_query(question)
        if fired:
            false_fire += 1
        print(f"generic {index}/{len(generic)} fired={fired}", flush=True)
    print(f"选择性: {len(generic) - false_fire}/{len(generic)} 未误激活", flush=True)

    total_hit = 0
    total = 0
    per_batch = {}
    for row in router_rows:
        facts = [json.loads(line) for line in (ROOT / "data" / f"batch_{row['batch']}.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        facts = [fact for fact in facts if fact.get("qa") and not fact.get("_common")]
        hit = 0
        for fact in facts:
            question, gold = fact["qa"][0]["q"], fact["qa"][0]["a"]
            best, _sim, fired = route_query(question)
            if fired:
                model.set_adapter(best)
                predicted = answer(model, tok, device, question)
            else:
                with model.disable_adapter():
                    predicted = answer(model, tok, device, question)
            ok = gold.rstrip("年") in predicted
            hit += int(ok)
            total += 1
            total_hit += int(ok)
            print(f"batch {row['batch']} {total} hit={ok} fired={fired} gold={gold} ans={predicted[:40]}", flush=True)
        per_batch[row["batch"]] = f"{hit}/{len(facts)}"
        print(f"批次 {row['batch']}: {hit}/{len(facts)}", flush=True)
    summary = {
        "false_fire": false_fire,
        "generic": len(generic),
        "hit": total_hit,
        "total": total,
        "per_batch": per_batch,
        "dtype": "float32",
        "device": "cpu",
        "tau": 0.6,
    }
    out = ROOT / ".cache" / "existing_experts_eval.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("EXISTING_EVAL", json.dumps(summary, ensure_ascii=False), flush=True)
    if false_fire != 0 or total_hit / total < 0.90:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

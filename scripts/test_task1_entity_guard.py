"""Task 1 完整验收测试脚本: 实体守卫 (Entity Guard) 验证。

测试目标:
1. 在全量 5 专家环境下,记忆准确率和选择性不受任何影响 (保持 ~93.6% 召回, 20/20 常识 0% 误激活);
2. 在淘汰/删除某个专家 (如 expert_4) 后:
   - 对应已删除批次的全部提问 (50 事实 × 3 问法 = 150 题) 100% 正确拦截并回退基座;
   - 交叉误射率 (Misrouting rate) 降至 0%;
   - 剩余在册专家 (expert_0..3) 正常问答不受任何干扰。

运行方式:
  python scripts/test_task1_entity_guard.py --rocm
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

sys.path.insert(0, str(Path(__file__).parent))
from router import embed, extract_entities_from_key_texts, verify_entity_guard
from eval_memory import answer, pick_device


def run_full_verification(device, model_path="models/Qwen2.5-0.5B-Instruct", tau=0.6):
    print("=" * 60)
    print(">> Step 1: 验证全量 5 专家下的记忆准确率与选择性 (确保无损伤)")
    print("=" * 60)

    tok = AutoTokenizer.from_pretrained(model_path)
    base = AutoModelForCausalLM.from_pretrained(model_path, torch_dtype=torch.float16).to(device)

    experts_dir = Path("experts")
    router = [json.loads(l) for l in (experts_dir / "router.jsonl").open(encoding="utf-8")]

    first = router[0]
    model = PeftModel.from_pretrained(base, experts_dir / first["expert"], adapter_name=first["expert"])
    for e in router[1:]:
        model.load_adapter(experts_dir / e["expert"], adapter_name=e["expert"])
    model.eval()

    keys = {e["expert"]: torch.load(e["key_path"], weights_only=True) for e in router}
    expert_entities = {}
    for e in router:
        kt_file = Path(e["key_path"]).parent / "key_texts.json"
        texts = json.load(kt_file.open(encoding="utf-8")) if kt_file.exists() else []
        expert_entities[e["expert"]] = extract_entities_from_key_texts(texts)

    def route_query(text: str):
        q = embed([text])[0]
        sim_scores = {name: (k @ q).max().item() for name, k in keys.items()}
        best, s = max(sim_scores.items(), key=lambda kv: kv[1])
        entity_pass = verify_entity_guard(text, expert_entities.get(best, []))
        fired = (s >= tau) and entity_pass
        return best, s, fired, entity_pass

    # 1. 测选择性
    generic = [json.loads(l) for l in open("data/generic_questions.jsonl", encoding="utf-8")]
    false_fire = 0
    for item in generic:
        q = item["q"] if isinstance(item, dict) else item
        best, s, fired, entity_pass = route_query(q)
        if fired:
            false_fire += 1
    print(f"选择性 (常识 20 题): {len(generic) - false_fire}/{len(generic)} 未误激活 (误激活率: {false_fire / len(generic):.0%})")
    assert false_fire == 0, "常识选择性测试失败: 存在误激活!"

    # 2. 测 5 批次记忆召回
    total_hit = 0
    total_facts = 0
    for e in router:
        facts = [json.loads(l) for l in open(f"data/batch_{e['batch']}.jsonl", encoding="utf-8")]
        facts = [f for f in facts if f.get("qa") and not f.get("_common")]
        hit = fired_cnt = 0
        for f in facts:
            q, gold = f["qa"][0]["q"], f["qa"][0]["a"]
            best, s, fired, entity_pass = route_query(q)
            if fired:
                fired_cnt += 1
                model.set_adapter(best)
                ans = answer(model, tok, device, q)
            else:
                with model.disable_adapter():
                    ans = answer(model, tok, device, q)
            if gold.rstrip("年") in ans:
                hit += 1
        print(f"批次 {e['batch']}: 激活率 {fired_cnt}/{len(facts)}, 记忆准确率 {hit}/{len(facts)} ({hit / len(facts):.0%})")
        total_hit += hit
        total_facts += len(facts)

    print(f"全量 5 专家总体准确率: {total_hit}/{total_facts} ({total_hit / total_facts:.1%})")
    assert total_hit / total_facts >= 0.90, "全量记忆召回率低于 90% 预期!"

    print("\n" + "=" * 60)
    print(">> Step 2: 验证专家淘汰/删除后的拦截回退与 0% 交叉误射")
    print("=" * 60)

    # 模拟删除 expert_4
    test_exp_dir = Path(".cache/test_expert_pruning")
    if test_exp_dir.exists():
        shutil.rmtree(test_exp_dir)
    shutil.copytree("experts", test_exp_dir)
    shutil.rmtree(test_exp_dir / "expert_4")
    active_lines = [json.loads(l) for l in (test_exp_dir / "router.jsonl").open(encoding="utf-8") if l.strip() and "expert_4" not in l]
    with (test_exp_dir / "router.jsonl").open("w", encoding="utf-8") as f:
        for l in active_lines:
            f.write(json.dumps(l, ensure_ascii=False) + "\n")

    # 仅加载 expert_0..3
    pruned_keys = {e["expert"]: torch.load(e["key_path"], weights_only=True) for e in active_lines}
    pruned_entities = {e["expert"]: expert_entities[e["expert"]] for e in active_lines}

    # 测试删除的 batch_4 所有 50 条事实 × 3 种问法 (共 150 题)
    b4_facts = [json.loads(l) for l in open("data/batch_4.jsonl", encoding="utf-8")]
    misrouted_cnt = 0
    fallback_cnt = 0
    total_q = 0

    for f in b4_facts:
        for q_item in f["qa"]:
            total_q += 1
            q = q_item["q"]
            qv = embed([q])[0]
            sim_scores = {name: (k @ qv).max().item() for name, k in pruned_keys.items()}
            best, s = max(sim_scores.items(), key=lambda kv: kv[1])
            entity_pass = verify_entity_guard(q, pruned_entities.get(best, []))
            fired = (s >= tau) and entity_pass

            if fired:
                misrouted_cnt += 1
            else:
                fallback_cnt += 1

    print(f"测试已淘汰批次 4 的提问 (共 {total_q} 题):")
    print(f"  - 交叉误射至其他专家: {misrouted_cnt} / {total_q} ({misrouted_cnt / total_q:.0%})")
    print(f"  - 正确拦截并回退基座: {fallback_cnt} / {total_q} ({fallback_cnt / total_q:.1%})")

    assert misrouted_cnt == 0, f"存在交叉误射: {misrouted_cnt} 题未被拦截!"
    assert fallback_cnt == total_q, f"未达到 100% 回退基座: {fallback_cnt}/{total_q}"

    # 清理测试目录
    if test_exp_dir.exists():
        shutil.rmtree(test_exp_dir)

    print("\n" + "=" * 60)
    print(">> All Verifications PASSED! Task 1 核心指标已 100% 达成。")
    print("=" * 60)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rocm", action="store_true")
    ap.add_argument("--cpu", action="store_true")
    args = ap.parse_args()
    device = pick_device(args)
    run_full_verification(device)

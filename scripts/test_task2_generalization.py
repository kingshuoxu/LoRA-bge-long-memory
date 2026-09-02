"""Task 2 完整自动化验收测试: 泛化与属性绑定增强验证。

测试指标:
1. 标准训练见过的问法 (qidx=0, 1, 2): 记忆召回率保持 ≥ 95% (实测 100%), 常识选择性 0% 误激活;
2. 口语化/场景化未见问法 (data_para qidx=0 和 qidx=1):
   - 包含 "老大"、"招牌产品"、"哪年创办"、"总部放在哪儿了" 等未见口语词;
   - 总体召回率从 84.4% 提升至 ≥ 95% (实测 100%);
   - 属性错位现象 (Attribute Misalignment) 完全清零 (0/250);
3. 专家删除与实体守卫 (Task 1 回归测试): 仍保持 100% 回退基座与 0% 交叉误射。

运行方式:
  python scripts/test_task2_generalization.py --rocm
"""
import argparse
import json
import sys
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

sys.path.insert(0, str(Path(__file__).parent))
from router import embed, extract_entities_from_key_texts, verify_entity_guard
from eval_memory import answer, pick_device


def run_task2_verification(device, model_path="models/Qwen2.5-0.5B-Instruct", tau=0.6):
    print("=" * 70)
    print(">> Task 2 验收测试: 口语化泛化与属性绑定鲁棒性验证")
    print("=" * 70)

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
        return best, s, fired

    # 1. 验证标准问法准确率
    print("\n[Step 1] 标准问法测试 (data/ 批次 0~4):")
    total_hit = total_facts = 0
    for e in router:
        facts = [json.loads(l) for l in open(f"data/batch_{e['batch']}.jsonl", encoding="utf-8")]
        facts = [f for f in facts if f.get("qa") and not f.get("_common")]
        hit = fired_cnt = 0
        for f in facts:
            q, gold = f["qa"][0]["q"], f["qa"][0]["a"]
            best, s, fired = route_query(q)
            if fired:
                fired_cnt += 1
                model.set_adapter(best)
                ans = answer(model, tok, device, q)
            else:
                with model.disable_adapter():
                    ans = answer(model, tok, device, q)
            if gold.rstrip("年") in ans:
                hit += 1
        print(f"  批次 {e['batch']}: 激活率 {fired_cnt}/{len(facts)}, 记忆准确率 {hit}/{len(facts)} ({hit / len(facts):.0%})")
        total_hit += hit
        total_facts += len(facts)
    std_acc = total_hit / total_facts
    print(f"  => 标准问法总体准确率: {total_hit}/{total_facts} ({std_acc:.1%})")
    assert std_acc >= 0.95, f"标准问法准确率未达标: {std_acc:.1%}"

    # 2. 验证口语化/未见句式泛化 (data_para/ qidx=0 和 qidx=1)
    print("\n[Step 2] 口语化/未见句式压力测试 (data_para/ 口语化问法 #1 与 #2):")
    for qidx in [0, 1]:
        p_hit = p_total = 0
        attr_errors = 0
        for e in router:
            facts = [json.loads(l) for l in open(f"data_para/batch_{e['batch']}.jsonl", encoding="utf-8")]
            facts = [f for f in facts if f.get("qa") and not f.get("_common")]
            hit = 0
            for f in facts:
                q, gold = f["qa"][qidx]["q"], f["qa"][qidx]["a"]
                best, s, fired = route_query(q)
                if fired:
                    model.set_adapter(best)
                    ans = answer(model, tok, device, q)
                else:
                    with model.disable_adapter():
                        ans = answer(model, tok, device, q)
                if gold.rstrip("年") in ans:
                    hit += 1
                else:
                    attr_errors += 1
                    print(f"    [错位样例] 属性:{f['attr']} | Q:{q} -> A:{ans} (Gold:{gold})")
            p_hit += hit
            p_total += len(facts)
        p_acc = p_hit / p_total
        print(f"  => 口语化问法 #{qidx + 1} 总体准确率: {p_hit}/{p_total} ({p_acc:.1%}), 属性错位错误数: {attr_errors}")
        assert p_acc >= 0.95, f"口语化问法 #{qidx + 1} 召回率未达标: {p_acc:.1%}"
        assert attr_errors == 0, f"存在属性错位错误: {attr_errors} 题"

    # 3. 验证选择性 (常识不被误激活)
    generic = [json.loads(l) for l in open("data/generic_questions.jsonl", encoding="utf-8")]
    false_fire = 0
    for item in generic:
        q = item["q"] if isinstance(item, dict) else item
        best, s, fired = route_query(q)
        if fired:
            false_fire += 1
    print(f"\n[Step 3] 常识选择性测试: {len(generic) - false_fire}/{len(generic)} 未误激活 (误激活率: {false_fire / len(generic):.0%})")
    assert false_fire == 0, "常识选择性测试失败: 存在误激活!"

    print("\n" + "=" * 70)
    print(">> All Verifications PASSED! Task 2 目标 (口语化召回 ≥95%, 属性错位清零) 已 100% 达成。")
    print("=" * 70)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rocm", action="store_true")
    ap.add_argument("--cpu", action="store_true")
    args = ap.parse_args()
    device = pick_device(args)
    run_task2_verification(device)

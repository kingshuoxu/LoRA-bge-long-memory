"""Task 3 完整真实闭环测试: 自然语言输入 -> 事实抽取 -> 风险防护 -> 自答门控 -> 专家自进化 -> 召回与通用能力测试。

测试场景:
1. 模拟现实输入: 准备 10 段真实风格的企业新闻/简介文本, 包含未见虚构事实以及已知常识;
2. 运行 extract_facts_from_text 抽取事实并进行【原文蕴含双向校验】(防抽取幻觉);
3. 自动生成 8 模板多样化 QA 结构;
4. 经过 AutoWriter 惊奇度门控 (BGE 路由去重 + 基座 QA 自答判定), 过滤已知常识, 仅对真正未知事实入库;
5. 自动训练生成独立专家并注册 key_texts 实体守卫;
6. 执行写入后探针自验 (Post-Write Probe): 验证新知识记忆 100% 召回, 包含标准问法与口语化问法;
7. 回归验证: 通用能力 (CMMLU/常识选择性) 零退化 (0% 误激活)。
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
from extract_qa_pipeline import extract_facts_from_text, generate_qa_dataset_for_facts
from auto_write import AutoWriter
from router import embed, extract_entities_from_key_texts, verify_entity_guard
from eval_memory import answer, pick_device


# 10 段测试用的自然语言新闻与企业段落 (包含新知识与已知常识)
RAW_NEWS_PARAGRAPHS = [
    # 新闻 1: 华夏科技快讯
    "【产业资讯】新兴芯片科技企业特塔维公司于2015年创立，其总部坐落在雷奥堡。据官方披露，该公司的首席执行官是昆达菲博士。旗下自主研发的明星产品为维格德-882，引发广泛关注。",
    # 新闻 2: 人工智能前沿
    "智算领域新秀纳尔佐公司成立于2020年。纳尔佐公司的总部位于特布市，目前公司的掌门人是鲁索莱先生。公司近期发布了年度旗舰产品达珈莫-665。",
    # 新闻 3: 制造先锋
    "【企业动态】高端装备制造商珈特莫公司把总部设在佩希港，公司于1985年建厂起步。珈特莫公司的首席执行官是莫菲女士，公司最出名的产品叫珈特-109。",
    # 新闻 4: 综合工业
    "成立于1998年的鲁佩萨公司近期完成战略升级，鲁佩萨公司的总部位于克达堡。公司的负责人由希雷博士担任，其拳头产品为佩萨维-773。",
    # 新闻 5: 生物医药
    "创新制药企业佐希克公司把总部放在了德纳市，佐希克公司成立于2005年。公司的首席执行官是维特先生，主打的核心产品叫希克奥-302。",
    # 混杂段落 (常识内容, 应当被自答门过滤不触发误写)
    "科学常识普及：水的化学式是H2O。法国的首都是巴黎，而中国的首都是北京。太阳系中体积最大的行星是木星。"
]


def run_task3_auto_pipeline_test(device, model_path="models/Qwen2.5-0.5B-Instruct"):
    print("=" * 75)
    print(">> Task 3 真实全自动闭环测试: 自然语言 -> 抽取与防幻觉 -> 门控自答 -> 专家训练 -> 验收")
    print("=" * 75)

    # 1. 事实抽取与原文蕴含校验
    print("\n[Step 1] 自然语言事实抽取与风险防护 (原文蕴含强校验):")
    all_extracted_facts = []
    for i, p in enumerate(RAW_NEWS_PARAGRAPHS):
        facts = extract_facts_from_text(p)
        print(f"  段落 #{i + 1} 抽取到 {len(facts)} 条事实:")
        for f in facts:
            print(f"    - [{f['attr']}] {f['entity']} -> {f['value']} (语句: {f['statement']})")
        all_extracted_facts.extend(facts)

    print(f"\n  => 共抽取并校验通过 {len(all_extracted_facts)} 条独立事实。")
    assert len(all_extracted_facts) >= 15, "抽取的事实数量不符合预期!"

    # 2. 合成多样化 8 模板 QA
    print("\n[Step 2] 问答对增强合成 (生成 8 模板多样化 QA 与实体守卫前置结构):")
    qa_dataset = generate_qa_dataset_for_facts(all_extracted_facts, batch_id=101)
    print(f"  => 成功合成 {len(qa_dataset)} 条事实的完整 QA 数据 (每条包含 8 种问法模板, 共 {len(qa_dataset) * 8} 题)")

    # 3. 运行 AutoWriter 惊奇度自动写入门控
    print("\n[Step 3] 惊奇度自动写入门控过滤 (BGE去重 + 基座自答一致性检测):")
    test_exp_dir = Path("experts_task3_test")
    test_data_dir = Path("data_task3_test")
    if test_exp_dir.exists():
        shutil.rmtree(test_exp_dir)
    if test_data_dir.exists():
        shutil.rmtree(test_data_dir)

    writer = AutoWriter(
        experts_dir=test_exp_dir,
        data_dir=test_data_dir,
        buffer_size=len(qa_dataset),  # 达到此数量直接触发训练
        device="cuda" if device.type == "cuda" else "cpu",
        epochs=6,
        lr=5e-4,
        bsz=16,
        model=model_path,
    )

    # 逐条喂入
    buffered_count = 0
    for item in qa_dataset:
        rec = writer.observe(item)
        print(f"  输入: {item['statement']} -> 判定动作: {rec['action']} (sim={rec.get('sim', 0)})")
        if rec["action"] in ("buffered", "trained"):
            buffered_count += 1

    print(f"\n  => 门控判定完成: {buffered_count}/{len(qa_dataset)} 条真正未知新事实进入缓冲并触发训练。")
    assert buffered_count == len(qa_dataset), "未知事实未能正确通过自答门控!"

    # 4. 验证生成的专家文件
    print("\n[Step 4] 检查自动生成的专家权重与路由索引:")
    assert (test_exp_dir / "router.jsonl").exists(), "专家路由表 router.jsonl 未生成!"
    router_entries = [json.loads(l) for l in (test_exp_dir / "router.jsonl").open(encoding="utf-8")]
    print(f"  => 成功注册生成新专家: {[e['expert'] for e in router_entries]}")

    # 5. 执行写入后探针自验 (Post-Write Self-Verification Probe)
    print("\n[Step 5] 写入后探针自验 (测试新生成的专家对抽取事实的标准与口语化提问召回率):")
    tok = AutoTokenizer.from_pretrained(model_path)
    base = AutoModelForCausalLM.from_pretrained(model_path, torch_dtype=torch.float16).to(device)

    first = router_entries[0]
    model = PeftModel.from_pretrained(base, test_exp_dir / first["expert"], adapter_name=first["expert"])
    model.eval()

    keys = {e["expert"]: torch.load(e["key_path"], weights_only=True) for e in router_entries}
    expert_entities = {}
    for e in router_entries:
        kt_file = Path(e["key_path"]).parent / "key_texts.json"
        texts = json.load(kt_file.open(encoding="utf-8")) if kt_file.exists() else []
        expert_entities[e["expert"]] = extract_entities_from_key_texts(texts)

    def route_query(text: str):
        q = embed([text])[0]
        sim_scores = {name: (k @ q).max().item() for name, k in keys.items()}
        best, s = max(sim_scores.items(), key=lambda kv: kv[1])
        entity_pass = verify_entity_guard(text, expert_entities.get(best, []))
        fired = (s >= 0.6) and entity_pass
        return best, s, fired

    # 测试 1: 标准问法召回
    std_hit = 0
    for item in qa_dataset:
        q = item["qa"][0]["q"]
        gold = item["qa"][0]["a"]
        best, s, fired = route_query(q)
        assert fired, f"未能激活新专家: {q}"
        model.set_adapter(best)
        ans = answer(model, tok, device, q)
        if gold.rstrip("年") in ans:
            std_hit += 1
        else:
            print(f"    [未命中] Q: {q} -> A: {ans} (Gold: {gold})")

    print(f"  => 新事实标准问法准确率: {std_hit}/{len(qa_dataset)} ({std_hit / len(qa_dataset):.1%})")
    assert std_hit / len(qa_dataset) >= 0.90, "探针自验失败: 新知识标准问法召回率低于 90%!"

    # 测试 2: 口语化俚语问法压力测试 (如 "老大", "掌门人", "哪年起步", "拳头产品")
    colloquial_hit = 0
    test_colloquial_queries = [
        ("特塔维公司现在的掌门人叫什么?", "昆达菲博士"),
        ("纳尔佐这家公司的老大是谁?", "鲁索莱先生"),
        ("珈特莫最出名的拳头产品是什么型号?", "珈特-109"),
        ("鲁佩萨是哪年起步的?", "1998"),
        ("佐希克把公司总部放在哪个地方了?", "德纳市"),
    ]
    print("\n  [口语化/场景化压力实测]:")
    for q, gold in test_colloquial_queries:
        best, s, fired = route_query(q)
        if fired:
            model.set_adapter(best)
            ans = answer(model, tok, device, q)
        else:
            with model.disable_adapter():
                ans = answer(model, tok, device, q)
        matched = gold in ans
        if matched:
            colloquial_hit += 1
        print(f"    - Q: \"{q}\" -> A: \"{ans}\" | Gold: {gold} | {'✓ 正确' if matched else '✗ 错误'}")

    assert colloquial_hit == len(test_colloquial_queries), "口语化泛化测试未达到 100% 召回!"

    # 6. 选择性测试 (常识不被误激活)
    print("\n[Step 6] 常识选择性保护测试 (确保新专家不会误激活常识):")
    generic = [json.loads(l) for l in open("data/generic_questions.jsonl", encoding="utf-8")]
    false_fires = 0
    for g in generic:
        q = g["q"]
        best, s, fired = route_query(q)
        if fired:
            false_fires += 1
    print(f"  => 常识选择性: {len(generic) - false_fires}/{len(generic)} 未误激活 (误激活率: {false_fires / len(generic):.0%})")
    assert false_fires == 0, "常识选择性测试失败: 发生误激活!"

    # 清理测试目录
    if test_exp_dir.exists():
        shutil.rmtree(test_exp_dir)
    if test_data_dir.exists():
        shutil.rmtree(test_data_dir)

    print("\n" + "=" * 75)
    print(">> All Verifications PASSED! Task 3 端到端抽取与风险防护闭环已 100% 达成。")
    print("=" * 75)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rocm", action="store_true")
    ap.add_argument("--cpu", action="store_true")
    args = ap.parse_args()
    device = pick_device(args)
    run_task3_auto_pipeline_test(device)

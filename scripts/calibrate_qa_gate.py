"""校准 2.0:问答置信度信号能否替代 perplexity 当写门?

思路:流场景里事实本身就带答案(用户说"X 的 Y 是 Z" → 问"X 的 Y 是什么?",gold=Z)。
让基座自答:
- 答对(命中 gold)→ 已知 → 不该写;
- 答错 → 未知 → 该写。
连续信号用 teacher-forced gold 答案 CE(低=已知),报 AUC;离散信号用命中与否。

对照 perplexity 信号(§9.1,AUC 0.876):本脚本在 0.5B 与 1.5B 上各测一次。

用法: python scripts/calibrate_qa_gate.py --rocm [--model models/Qwen2.5-1.5B-Instruct]
"""
import argparse
import json
import sys
from pathlib import Path

import torch
import torch.nn.functional as F

sys.path.insert(0, str(Path(__file__).parent))
from train_expert import pick_device
from transformers import AutoModelForCausalLM, AutoTokenizer

# 与 COMMON_STATEMENTS 对齐的 (问题, 答案) 对;gold 用模型惯用形式(阿拉伯数字),
# 匹配时经 _norm 归一化(下标数字→普通数字,去空格)
COMMON_QA = [
    ("水的化学式是什么?", "H2O"), ("一年有多少个月?", "12"), ("法国的首都是哪里?", "巴黎"),
    ("地球绕太阳公转一周大约需要多久?", "365"), ("三角形的内角和是多少度?", "180"),
    ("中国的首都是哪里?", "北京"), ("冰在标准大气压下多少度融化?", "0"),
    ("一周有几天?", "7"), ("光速大约是多少?", "30万"), ("莎士比亚是哪国人?", "英"),
    ("水在标准大气压下多少度沸腾?", "100"), ("中国的官方语言是什么?", "汉语"),
    ("氧气在空气中大约占多少?", "21"), ("太阳系最大的行星是哪颗?", "木星"),
    ("人体最大的器官是什么?", "皮肤"), ("月亮是行星还是卫星?", "卫星"),
    ("光合作用发生在植物的哪个细胞器中?", "叶绿体"), ("CPU 的全称是什么?", "中央处理器"),
    ("英语中苹果怎么拼?", "apple"), ("日本的首都是哪里?", "东京"),
    ("世界上最高的山峰是什么?", "珠穆朗玛峰"), ("中国第二长河是哪条河?", "黄河"),
    ("人体正常体温大约多少摄氏度?", "37"), ("一天有多少小时?", "24"),
    ("声音和光哪个传播快?", "光"), ("陆地上最大的哺乳动物是什么?", "大象"),
    ("气压降低时水的沸点会升高还是降低?", "降低"), ("地球自转方向是什么?", "自西向东"),
    ("哪种维生素广泛存在于新鲜水果中?", "维生素C"), ("蜜蜂通过什么传递蜜源位置?", "跳舞"),
    ("空气中含量最多的气体是什么?", "氮气"), ("人体有多少块骨骼?", "206"),
    ("鲸鱼是鱼类还是哺乳动物?", "哺乳动物"), ("彩虹通常什么时候出现?", "雨后"),
    ("铁的化学符号是什么?", "Fe"), ("中国历史上第一位皇帝是谁?", "秦始皇"),
    ("长城是哪个国家的著名建筑?", "中国"), ("熊猫主要吃什么?", "竹子"),
    ("地球表面大约百分之多少被海洋覆盖?", "71"), ("光年是长度单位还是时间单位?", "长度"),
    ("人眼的像素大约相当于多少?", "数亿"), ("声音能在真空中传播吗?", "不能"),
    ("植物通过什么吸收水分?", "根"), ("遗传信息的载体是什么?", "DNA"),
    ("太阳是恒星还是行星?", "恒星"), ("火星因富含什么而呈红色?", "氧化铁"),
    ("企鹅主要生活在哪个半球?", "南"), ("沙漠地区昼夜温差大吗?", "大"),
    ("蝙蝠依靠什么定位?", "超声波"), ("人类血型主要分为哪几种?", "A"),
]
assert len(COMMON_QA) == 50

_SUB = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")


def _norm(s: str) -> str:
    return s.translate(_SUB).replace(" ", "")


@torch.no_grad()
def self_answer(model, tok, device, question: str) -> str:
    messages = [{"role": "system", "content": "你是助手。"},
                {"role": "user", "content": question + " 请简短回答。"}]
    text = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tok(text, return_tensors="pt").to(device)
    out = model.generate(**inputs, max_new_tokens=40, do_sample=False,
                         pad_token_id=tok.eos_token_id)
    return tok.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()


@torch.no_grad()
def gold_answer_ce(model, tok, device, question: str, gold: str) -> float:
    """teacher-forced:问题之后接 gold 答案的逐 token CE(低=模型觉得答案理所当然)。"""
    messages = [{"role": "system", "content": "你是助手。"},
                {"role": "user", "content": question + " 请简短回答。"}]
    prompt = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    p_ids = tok(prompt, add_special_tokens=False)["input_ids"]
    a_ids = tok(gold, add_special_tokens=False)["input_ids"]
    ids = torch.tensor([p_ids + a_ids], device=device)
    causal = model.get_base_model() if hasattr(model, "get_base_model") else model
    hidden = causal.model(input_ids=ids).last_hidden_state
    h = hidden[0, len(p_ids) - 1:-1, :]  # 预测答案各 token 的位置
    logits = causal.lm_head(h)
    return F.cross_entropy(logits.float(), ids[0, len(p_ids):]).item()


def auc(pos: list[float], neg: list[float]) -> float:
    gt = sum(p > n for p in pos for n in neg)
    eq = sum(p == n for p in pos for n in neg)
    return (gt + 0.5 * eq) / (len(pos) * len(neg))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="models/Qwen2.5-0.5B-Instruct")
    ap.add_argument("--n", type=int, default=100, help="虚构事实取样条数")
    ap.add_argument("--cpu", action="store_true")
    ap.add_argument("--rocm", action="store_true")
    args = ap.parse_args()

    device = pick_device(args)
    tok = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForCausalLM.from_pretrained(args.model, torch_dtype=torch.float32).to(device)
    model.eval()
    print(f"模型 {args.model},设备 {device}", flush=True)

    facts = []
    for k in range(5):
        facts += [json.loads(l) for l in open(f"data/batch_{k}.jsonl", encoding="utf-8")]
    items = ([(f["qa"][0]["q"], f["qa"][0]["a"], True) for f in facts[:args.n]]  # True=该写
             + [(q, a, False) for q, a in COMMON_QA])

    ce_write, ce_skip = [], []
    n_hit_write = n_hit_skip = 0
    for i, (q, gold, should_write) in enumerate(items):
        ans = self_answer(model, tok, device, q)
        hit = _norm(gold.rstrip("年")) in _norm(ans)
        ce = gold_answer_ce(model, tok, device, q, gold)
        (ce_write if should_write else ce_skip).append(ce)
        if should_write:
            n_hit_write += hit  # 事实被答对=漏写风险
        else:
            n_hit_skip += hit   # 常识被答对=正确跳过
        if (i + 1) % 25 == 0:
            print(f"  {i + 1}/{len(items)}", flush=True)

    nf, nc = len(ce_write), len(ce_skip)
    print(f"\n== QA 置信度信号({args.model}) ==")
    print(f"虚构事实:基座答对 {n_hit_write}/{nf}(应≈0,答对=漏写风险)")
    print(f"常识:    基座答对 {n_hit_skip}/{nc}(应接近 {nc},答对=正确跳过)")
    print(f"门指标(答错才写):事实召回 {(nf - n_hit_write) / nf:.1%},常识误写 {(nc - n_hit_skip) / nc:.1%}")
    print(f"gold 答案 CE:事实 mean={sum(ce_write) / nf:.3f},常识 mean={sum(ce_skip) / nc:.3f},"
          f"AUC={auc(ce_write, ce_skip):.3f}")


if __name__ == "__main__":
    main()

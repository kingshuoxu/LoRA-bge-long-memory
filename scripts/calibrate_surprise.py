"""surprise 校准:基座 token loss 能否分开"该写的虚构事实"与"不该写的常识"?

三类文本的逐 token 平均 CE(基座、纯文本、无 chat 模板):
  (a) 虚构事实陈述句(data/batch_*.jsonl,该写);
  (b) 常识陈述句(本文件内置 50 条,不该写);
  (c) 参照:已记忆事实在 adapter 开/关下的 loss(验证"写入=loss 下降"闭环)。

产出:(a)/(b) 分布直方图 docs/surprise_calibration.png、AUC、Youden 阈值建议。
若 AUC 明显 <0.95,按方案降级(路由 + 对话反馈信号为主)。

用法: python scripts/calibrate_surprise.py --rocm
"""
import argparse
import json
import sys
from pathlib import Path

import torch
import torch.nn.functional as F
from transformers import AutoModelForCausalLM, AutoTokenizer

sys.path.insert(0, str(Path(__file__).parent))
from train_expert import pick_device

MODEL = "models/Qwen2.5-0.5B-Instruct"

# 常识陈述句:与虚构事实同样的"X 是/有 Y" declarative 句式,保证分布对比公平
COMMON_STATEMENTS = [
    "水的化学式是H₂O。", "一年有十二个月。", "法国的首都是巴黎。",
    "地球绕太阳公转一周大约需要三百六十五天。", "三角形的内角和是一百八十度。",
    "中国的首都是北京。", "冰在标准大气压下零摄氏度融化。", "一周有七天。",
    "光速大约是每秒三十万公里。", "莎士比亚是英国人。", "水沸腾的温度是一百摄氏度。",
    "中国的官方语言是汉语。", "氧气在空气中大约占百分之二十一。", "太阳系最大的行星是木星。",
    "人体最大的器官是皮肤。", "月亮是地球的卫星。", "光合作用发生在植物的叶绿体中。",
    "计算机的CPU全称是中央处理器。", "英语中苹果拼作apple。", "日本的首都是东京。",
    "世界上最高的山峰是珠穆朗玛峰。", "黄河是中国第二长河。", "人体的正常体温约为三十七摄氏度。",
    "一天有二十四个小时。", " Sound travels slower than light.",  # 混入一条英文噪声
    "大象是陆地上最大的哺乳动物。", "水的沸点随气压降低而降低。", "地球的自转方向是自西向东。",
    "维生素C广泛存在于新鲜水果中。", "蜜蜂通过跳舞传递蜜源位置信息。", "空气中含量最多的气体是氮气。",
    "人体的骨骼共有二百零六块。", "鲸鱼是哺乳动物而不是鱼类。", "彩虹通常出现在雨后的天空。",
    "铁的化学符号是Fe。", "秦始皇是中国历史上第一位皇帝。", "长城是中国的著名古代建筑。",
    "熊猫主要以竹子为食。", "地球表面约百分之七十一被海洋覆盖。", "光年是长度单位而不是时间单位。",
    "人眼的像素相当于数亿级别。", "声音在真空中无法传播。", "植物通过根系吸收水分。",
    "DNA是遗传信息的载体。", "太阳是一颗恒星。", "火星因富含氧化铁而呈红色。",
    "企鹅主要生活在南半球。", "沙漠地区的昼夜温差很大。", "蝙蝠依靠超声波定位。",
    "人类的血型主要分为A、B、AB、O四种。",
]


@torch.no_grad()
def mean_token_loss(model, tok, device, texts: list[str], bsz: int = 32) -> torch.Tensor:
    """纯文本逐 token 平均 CE(shift 对齐),返回 (n,) CPU 张量。"""
    losses = []
    for i in range(0, len(texts), bsz):
        batch = tok(texts[i:i + bsz], padding=True, truncation=True,
                    max_length=128, return_tensors="pt").to(device)
        ids, attn = batch["input_ids"], batch["attention_mask"]
        # 兼容裸模型与 PeftModel(get_base_model 拿到带 LoRA 注入的 CausalLM)
        causal = model.get_base_model() if hasattr(model, "get_base_model") else model
        hidden = causal.model(input_ids=ids, attention_mask=attn).last_hidden_state
        h, l = hidden[:, :-1, :], ids[:, 1:]
        mask = l != tok.pad_token_id
        logits = causal.lm_head(h[mask])
        ce = F.cross_entropy(logits.float(), l[mask], reduction="none")
        # 按行统计:每行取其 mask 位置的 ce 均值
        per_row = []
        start = 0
        counts = mask.sum(1)
        for c in counts:
            per_row.append(ce[start:start + c].mean())
            start += c
        losses.append(torch.stack(per_row))
    return torch.cat(losses).cpu()


def auc(pos: torch.Tensor, neg: torch.Tensor) -> float:
    """rank 法 AUC:P(pos 样本 loss > neg 样本 loss)。"""
    gt = (pos.unsqueeze(1) > neg.unsqueeze(0)).float().mean().item()
    eq = (pos.unsqueeze(1) == neg.unsqueeze(0)).float().mean().item()
    return gt + 0.5 * eq


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100, help="(a) 类取样条数")
    ap.add_argument("--model", default=MODEL, help="基座模型路径(对照更大模型用)")
    ap.add_argument("--cpu", action="store_true")
    ap.add_argument("--rocm", action="store_true")
    args = ap.parse_args()

    device = pick_device(args)
    tok = AutoTokenizer.from_pretrained(args.model)
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token
    base = AutoModelForCausalLM.from_pretrained(args.model, torch_dtype=torch.float32).to(device)
    base.eval()

    facts = []
    for k in range(5):
        facts += [json.loads(l) for l in open(f"data/batch_{k}.jsonl", encoding="utf-8")]
    a_texts = [f["statement"] for f in facts[:args.n]]
    b_texts = COMMON_STATEMENTS

    print(f"设备 {device};(a) 虚构事实 {len(a_texts)} 条,(b) 常识 {len(b_texts)} 条", flush=True)
    la = mean_token_loss(base, tok, device, a_texts)
    lb = mean_token_loss(base, tok, device, b_texts)

    print(f"\n(a) 虚构事实 loss: mean={la.mean():.3f} p5={la.quantile(0.05):.3f} p95={la.quantile(0.95):.3f}")
    print(f"(b) 常识陈述 loss: mean={lb.mean():.3f} p5={lb.quantile(0.05):.3f} p95={lb.quantile(0.95):.3f}")
    a = auc(la, lb)
    print(f"AUC((a)>(b)) = {a:.3f}")

    # Youden 阈值:在候选阈值上最大化 TPR-FPR(把 loss>阈值判为"该写")
    cand = torch.linspace(min(la.min(), lb.min()), max(la.max(), lb.max()), 200)
    tpr = [(la > t).float().mean() for t in cand]
    fpr = [(lb > t).float().mean() for t in cand]
    j = [t - f for t, f in zip(tpr, fpr)]
    best = int(torch.tensor(j).argmax())
    print(f"建议阈值(Youden): loss > {cand[best]:.3f} → 召回 {tpr[best]:.1%},误写率 {fpr[best]:.1%}")

    # (c) 参照:已记忆事实在 adapter 开/关下的 loss(仅默认 0.5B 基座有已训专家)
    if Path(args.model) == Path(MODEL):
        from peft import PeftModel
        model = PeftModel.from_pretrained(base, "experts/expert_0", adapter_name="expert_0")
        c_texts = [f["statement"] for f in
                   (json.loads(l) for l in open("data/batch_0.jsonl", encoding="utf-8"))]
        c_texts = c_texts[:50]
        with model.disable_adapter():
            lc_off = mean_token_loss(model, tok, device, c_texts)
        model.set_adapter("expert_0")
        lc_on = mean_token_loss(model, tok, device, c_texts)
        print(f"\n(c) 参照(批次 0,已写入):adapter 关 {lc_off.mean():.3f} → 开 {lc_on.mean():.3f}"
              f"(写入使 loss 下降 {(1 - lc_on.mean() / lc_off.mean()):.0%})")

    # 直方图
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei"]
    fig, ax = plt.subplots(figsize=(7, 4.5))
    bins = 30
    ax.hist(lb.numpy(), bins=bins, alpha=0.6, label=f"(b) 常识(不该写) n={len(lb)}", color="#2563eb")
    ax.hist(la.numpy(), bins=bins, alpha=0.6, label=f"(a) 虚构事实(该写) n={len(la)}", color="#dc2626")
    ax.axvline(cand[best], color="black", ls="--", label=f"建议阈值 {cand[best]:.2f}")
    ax.set_xlabel("基座逐 token 平均 loss(纯文本)")
    ax.set_ylabel("条数")
    ax.set_title(f"surprise 校准:AUC = {a:.3f}")
    ax.legend()
    fig.tight_layout()
    out = Path("docs/surprise_calibration.png")
    fig.savefig(out, dpi=150)
    print(f"\n已保存 {out}")


if __name__ == "__main__":
    main()

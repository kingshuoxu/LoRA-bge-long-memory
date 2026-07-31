"""容量曲线:单 LoRA(r=32)记忆准确率 vs 事实条数。

结果数据由实验填入 RESULTS,运行: python scripts/plot_capacity.py
产出 docs/capacity_curve.png
"""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False

# (事实条数, 记忆准确率%, 备注)
# 50: 首批 5 专家实验均值(docs/experiment-results.md)
# 100~1000: 容量实验,lr 5e-4、21~30 epochs、bsz 64、ROCm 训练;
#           每档评测前 200 条事实,n=1000 另测尾部 200 条(skip 700)同为 100%
RESULTS = [
    (50, 93.6, "首批实验(5 专家均值)"),
    (100, 100.0, ""),
    (200, 100.0, ""),
    (500, 100.0, ""),
    (1000, 100.0, ""),
]

xs = [r[0] for r in RESULTS if r[1] is not None]
ys = [r[1] for r in RESULTS if r[1] is not None]

fig, ax = plt.subplots(figsize=(7, 4.5))
ax.plot(xs, ys, "o-", color="#2563eb", lw=2, ms=7)
for x, y in zip(xs, ys):
    ax.annotate(f"{y:.0f}%", (x, y), textcoords="offset points", xytext=(0, 9), ha="center")
ax.set_xscale("log")
ax.set_xticks(xs)
ax.set_xticklabels([str(x) for x in xs])
ax.set_ylim(0, 105)
ax.set_xlabel("单个 LoRA 专家训练的事实条数(log 刻度)")
ax.set_ylabel("记忆准确率(QA 命中)")
ax.set_title("容量曲线:一个 LoRA(r=32, 13M 参数)能装下多少条事实?")
ax.grid(alpha=0.3)
fig.tight_layout()

out = Path("docs/capacity_curve.png")
fig.savefig(out, dpi=150)
print(f"已保存 {out}")

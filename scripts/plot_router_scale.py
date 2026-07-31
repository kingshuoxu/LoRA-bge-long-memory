"""路由扩展性曲线:专家数 E vs 路由边际/准确率。

结果数据由实验填入(见 docs/experiment-results.md §8):
- E≤50 用每条事实 3 种问法做查询;E=100/200 用 1 种(省时)。
运行: python scripts/plot_router_scale.py → docs/router_scale.png
"""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False

# (E, top-1 路由准确率%, 边际 min, 边际中位, 常识误激活%)
RESULTS = [
    (5, 100.0, 0.019, 0.137, 0.0),
    (10, 100.0, 0.012, 0.113, 0.0),
    (25, 100.0, 0.003, 0.093, 0.0),
    (50, 100.0, 0.003, 0.078, 0.0),   # 3 问法;1 问法轮次为 0.004/0.097
    (100, 100.0, 0.004, 0.082, 0.0),
    (200, 100.0, 0.004, 0.070, 0.0),
]

es = [r[0] for r in RESULTS]
mmin = [r[2] for r in RESULTS]
mmed = [r[3] for r in RESULTS]

fig, ax = plt.subplots(figsize=(7, 4.5))
ax.plot(es, mmed, "s-", color="#2563eb", lw=2, ms=6, label="边际中位数")
ax.plot(es, mmin, "o-", color="#dc2626", lw=2, ms=6, label="边际最小值")
for x, y in zip(es, mmin):
    ax.annotate(f"{y:.3f}", (x, y), textcoords="offset points", xytext=(0, -14), ha="center", fontsize=8)
ax.axhline(0, color="gray", lw=1, ls="--", alpha=0.6)
ax.set_xscale("log")
ax.set_xticks(es)
ax.set_xticklabels([str(e) for e in es])
ax.set_xlabel("共存专家数 E(log 刻度)")
ax.set_ylabel("路由边际(自家最高 sim − 最强别家 sim)")
ax.set_title("路由扩展性:E 到 200(1 万条事实)top-1 准确率 100%,误激活 0%\n"
             "最小边际在 0.003~0.004 企稳——扩展受限于事实分布的最近邻密度,而非 E")
ax.grid(alpha=0.3)
ax.legend()
fig.tight_layout()

out = Path("docs/router_scale.png")
fig.savefig(out, dpi=150)
print(f"已保存 {out}")

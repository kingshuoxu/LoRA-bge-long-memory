# LoRA-bge-long-memory

用 **bge 检索 + LoRA 专家池**给稠密 LLM 做"权重级长期记忆"：事实被训练进独立的 LoRA 专家（权重即记忆，不占用 prompt / KV cache)，由 bge 语义索引自动路由挂载。在 Qwen2.5-0.5B / 1.5B 双基座上都跑通了全量验证。

## 总体思想

LLM 的"长期记忆"目前主要有两种形态，都有硬伤：

- **prompt / 上下文记忆**：塞进 context，占 token、随窗口丢弃，成本随长度增长；
- **RAG**：检索的是文本，模型要"现场阅读"才能回答——本质还是 prompt 记忆；
- **直接微调写入**：权重即记忆，但灾难性遗忘（学新忘旧），且动了基座、无法管理单条记忆。

本仓库验证第三条路线：**把记忆写进权重，但每批记忆隔离成一个独立的 LoRA 专家文件**：

```
写入: 新事实 → 训练一个 LoRA 专家 → 注册进 bge 索引
        ↑ 自动门(bge 去重 + QA 自答一致性): 拒重复/已知,误写率 72%→16%
读取: 问题 → bge 检索 top-1 → 相似度 > τ=0.6 → 挂载对应 LoRA → 生成
        ↑ 低于阈值 → 原生基座回答(通用能力零退化)
```

记忆从"边看边答"(RAG）变成"早已记住"（权重）；每条记忆 = 一个几 MB 的 adapter 文件，可增删、备份、分发、组合、版本化，且完全不动基座——这是 prompt 记忆和全量微调都不具备的工程性质。

## 这项工作的真正意义（诚实定位）

**先说清楚：架构不是首创。** "LoRA 专家池 + 检索路由"在学界已有先行/并行工作（参数化 RAG 的 P-RAG/DyPRAG 系列、Adaptive Minds、LoRAMoE 等，见下节）。本仓库的价值不在提出新架构，而在三件学术论文通常不做或不展开的事：

1. **用反事实对照给出因果证据**。"参数隔离防遗忘"很多论文当常识引用，这里给出了干净的对照：同一个 LoRA、同样的数据、同样的训练预算，顺序续训后旧批记忆只剩 **0~12%**；拆成专家后 **82~100%**(G2 对照，`docs/experiment-results.md` §7)。这是"每批经验一个专家"架构存在的定量理由。
2. **把自动写入门做到可用，并完整记录信号换代过程**。perplexity 门误写 72%（信号太弱，AUC 仅 0.876)→ QA 自答门误写 16%（让基座自答、答错才写）。途中修正了两个评估陷阱："读阈值误当写阈值"（首轮召回仅 16.8%）和"误激活率冤案"（激活且答对不算损伤；真实有效损伤仅 1/20)(§9)。
3. **诚实标定边界与上限**。bge 单层路由实测 200 专家 / 1 万条事实零错误；τ∈[0.55,0.95] 安全域内行为不变；单 LoRA(r=32）装 1000 条事实不饱和。同时暴露两个真实失效模式——**条件反射边界**（换问法可能失配）与**晚期发散**（收敛后继续训练会擦除记忆，早停是记忆生命周期管理的一部分，§4)。

它不是方法创新论文的配套代码，是一份**可复现、可证伪的工程研究日志**——把一条已被提出的路线的因果结论夯实、边界量化、坑全部记录在案（含 DirectML 不可训练、LLM 隐向量各向异性不能做路由键等 6 个失败模式，§3)。想真正落地这条路线的人，看这份日志比看只报喜不报忧的论文有用。

## 思想来源与参考工作

设计直接借用了以下工作（完整清单与链接见 `papers/README.md`):

| 来源 | 借用了什么 |
|---|---|
| **Lifelong-MoE / LoRAMoE / MoRAL**(LoRA-MoE 持续学习线） | 核心载体：新经验 → 新 LoRA 专家，参数隔离天然防覆盖 |
| **Titans / ATLAS**(Google，测试时参数记忆） | 写入控制：surprise（意外度）决定写不写——本仓库落地为 bge 去重 + QA 自答门 |
| **P-RAG → DyPRAG → Latent Routing**（参数化 RAG 线） | 并行实践：每篇文档一个 LoRA、推理时检索 adapter 挂载；证明同架构有效 |
| **Adaptive Minds / PEAM / Selective Parametric Consolidation** | 并行实践：agent 场景"每域/每经验一个 LoRA + 语义路由" |
| **LoraRetriever / PMDRouter** | LoRA 池的输入感知检索与路由基准（本仓库用外挂 bge；内生路由是下一步） |
| **Sleep-time Compute / Nested Learning (HOPE)** | 下一步方向：sleep-time 蒸馏合并专家、按更新频率分层记忆 |
| **Memory Layers at Scale / MoVE**(Meta 等） | 参数记忆规模化的形态参照 |

与这些工作的关系：本仓库不追求更大规模、不做学习型路由，而是补上它们普遍省略的**对照实验与边界标定**(G2 反事实、写门信号校准、τ 安全域、路由压测、双基座规模稳定性）。

## 核心结论（全部实测）

| 验证 | 0.5B | 1.5B |
|---|---|---|
| H1 记忆写入（事实 recall) | 93.6% | **100%** |
| H2 选择性（未学事实误激活） | 0% | 0% |
| H3 不遗忘（旧专家，5 批后） | 82~100% | ✓ |
| G2 反事实：单 LoRA 续训则旧批只剩 0~12% | ✓ | ✓(0/0/2/10/100%) |
| 路由扩展性（E=5→200 零错误、零常识误激活） | ✓ | — |
| 自动写入门（QA 自答信号，常识误写率） | 16% | 12% |
| 通用能力（CMMLU 10 科×30 题，router vs base) | **零退化** | **零退化** |
| 单 LoRA 容量（r=32) | ≥1000 条不饱和 | — |

关键结论：

- **方案成立**：外挂 LoRA 池可以实现权重级长期记忆——能写入、有选择性、不遗忘、可路由、可自动写入、不伤通用能力；0.5B→1.5B 方向一致（规模稳定）。
- **"不遗忘"来自参数隔离本身**(G2 对照），不是任务简单或训练技巧。
- **安全域很宽**:bge 相似度 τ∈[0.55, 0.95] 内读取路由与写门行为不变（事实 query≈0.70–0.88，通用 query≤0.54)，阈值不是玄学。
- **条件反射机制**：专家记住的是"问题的训练表述→答案"的触发反射，换说法可能失配——这是当前形态的真实边界。
- **训练有"晚期发散"坑**：收敛后继续训练会擦除已写入的记忆，需早停（§4)。

全部数字、失败迭代与阈值标定见 `docs/experiment-results.md`(12 节主文档）；设计动机见 `docs/experiment-design.md`。

## 复现

```bash
pip install torch transformers peft   # torch 按平台选 CUDA/ROCm/CPU 轮子
# 模型不入库,先下载到 models/(HF,国内可用 hf-mirror.com):
#   Qwen2.5-0.5B-Instruct(及可选 Qwen2.5-1.5B-Instruct)、bge-small-zh-v1.5
# data/(5 批×50 条虚构事实)已入库,也可用 python scripts/gen_data.py 重新生成

# ① 写入:逐批训 5 个 LoRA 专家(--rocm 走 GPU;--cpu 慢约 15 倍;DirectML 实测 gemm 落 CPU,勿用)
for k in 0 1 2 3 4; do
  python scripts/train_expert.py --batch $k --rank 32 --lr 1e-3 --epochs 12 --rocm
done
# 1.5B 全栈:加 --model models/Qwen2.5-1.5B-Instruct --out experts_15b --lr 5e-4 --epochs 21 --bsz 32
#           (1.5B fp32 下 bsz 64 会原生层 OOM,必须 32)

# ② 读取:记忆准确率 + 选择性(τ 默认 0.6;--sweep 只打印相似度分布)
python scripts/eval_memory.py --rocm
# 1.5B:加 --experts experts_15b --model models/Qwen2.5-1.5B-Instruct

# ③ 扩展实验
python scripts/g2_control.py --rocm              # 反事实对照:单 LoRA 续训的灾难性遗忘
python scripts/router_scale.py                   # 路由扩展性 E=5→200(纯 bge,不需训练)
python scripts/auto_write_demo.py                # surprise 自动写入门端到端(1.5B:--model ... --tag _15b --bsz 32)
python scripts/calibrate_surprise.py             # 写门信号校准:perplexity 分布与 AUC
python scripts/calibrate_qa_gate.py              # 写门信号校准:QA 自答一致性
python scripts/eval_general.py --rocm --tau 0.6  # 通用能力基准,需 CMMLU:
#   curl -sLO https://hf-mirror.com/datasets/lmlmcat/cmmlu/resolve/main/cmmlu_v1_0_1.zip
#   unzip -o cmmlu_v1_0_1.zip -d data_bench/
```

建议阅读顺序：`README` → `docs/experiment-design.md`（假设与分组）→ `docs/experiment-results.md`（结果、失败模式与边界）。

## 仓库结构

- `scripts/` — 训练 / 评测 / 路由 / 容量 / 基准 / 自动门 / 校准，各脚本 docstring 含用法；`scripts/debug/` 排障工具
- `docs/experiment-results.md` — 12 节实验主文档；`docs/experiment-design.md` — 设计文档；三张图（capacity_curve / router_scale / surprise_calibration)
- `data/`、`data_capacity/` — 虚构事实数据（已入库，`gen_data.py` 可确定性复现）
- `experts/` — 0.5B 五专家 LoRA 权重（git LFS)
- `papers/` — 前沿论文清单与 PDF（本地调研资料，gitignored 不入库）
- 1.5B 专家（`experts_15b/`)、自动门产出（`data_auto*/`)、CMMLU(`data_bench/`）不入库，用上面的命令复现

## 局限（明示）

专家**只增不改**：更新/删除记忆需要重训或淘汰机制（未做）；事实需以问答对形式写入，陈述句→问题的自动转换未做；自答信号存在"瞎猜猜中"的理论风险（250 条中观测到 1 例）；路由是外挂 bge 检索，真 MoE 层内路由（OLMoE 式）是下一步方向，未实现。

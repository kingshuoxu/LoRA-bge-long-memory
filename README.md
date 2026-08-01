# LoRA-bge-long-memory

用 **bge 检索 + LoRA 专家池**给稠密 LLM 做"权重级长期记忆"：事实被训练进独立的 LoRA 专家（权重即记忆，不占用 prompt / KV cache)，由 bge 语义索引自动路由挂载。在 Qwen2.5-0.5B / 1.5B 双基座上完成全量验证。

```
写入: 新事实 → 训练一个 LoRA 专家 → 注册进 bge 索引
        ↑ 自动门(bge 去重 + QA 自答一致性): 拒重复/旧值,误写率 72%→16%
读取: 问题 → bge 检索 top-1 → 相似度 > τ=0.6 → 挂载对应 LoRA → 生成
        ↑ 低于阈值 → 原生基座回答(通用能力零退化)
```

## 验证矩阵（全部实测通过）

| 验证 | 0.5B | 1.5B |
|---|---|---|
| H1 记忆写入（事实 recall) | 93.6% | **100%** |
| H2 选择性（未学事实误激活） | 0% | 0% |
| H3 不遗忘（旧专家，5 批后） | 82~100% | ✓ |
| G2 反事实：单 LoRA 续训则旧批只剩 0~12% | ✓ | — |
| 路由扩展性（E=5→200 零错误、零常识误激活） | ✓ | — |
| 自动写入门（QA 自答信号，常识误写率） | 16% | 12% |
| 通用能力（CMMLU 10 科×30 题，router vs base) | **零退化** | **零退化** |
| 单 LoRA 容量（r=32) | ≥1000 条不饱和 | — |

全部数字、失败迭代与阈值标定见 `docs/experiment-results.md`(12 节主文档）。

## 关键结论

- **方案成立**：外挂 LoRA 池可以实现权重级长期记忆——能写入、有选择性、不遗忘、可路由、可自动写入、不伤通用能力；0.5B→1.5B 结论方向一致（规模稳定）。
- **"不遗忘"来自参数隔离本身**(G2 对照）：同一个 LoRA 顺序续训同样数据，旧批全军覆没（0~12%)；分成专家后 82~100%。
- **安全域很宽**:bge 相似度 τ∈[0.55, 0.95] 内读取路由与写门行为不变（事实 query≈0.70–0.88，通用 query≤0.54)，阈值不是玄学。
- **条件反射机制**：专家记住的是"问题的训练表述→答案"的触发反射，换说法可能失配——这是当前形态的真实边界。
- **训练有"晚期发散"坑**：收敛后继续训练会擦除已写入的记忆，需早停（§4)。

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
python scripts/eval_general.py --rocm --tau 0.6  # 通用能力基准,需 CMMLU:
#   curl -sLO https://hf-mirror.com/datasets/lmlmcat/cmmlu/resolve/main/cmmlu_v1_0_1.zip
#   unzip -o cmmlu_v1_0_1.zip -d data_bench/
```

## 仓库结构

- `scripts/` — 训练 / 评测 / 路由 / 容量 / 基准 / 自动门，各脚本 docstring 含用法；`scripts/debug/` 排障工具
- `docs/experiment-results.md` — 12 节实验主文档；`docs/experiment-design.md` — 设计文档；三张图（capacity_curve / router_scale / surprise_calibration)
- `data/`、`data_capacity/` — 虚构事实数据（已入库，`gen_data.py` 可确定性复现）
- `experts/` — 0.5B 五专家 LoRA 权重（git LFS)
- `papers/` — 前沿论文清单与 PDF（本地调研资料，gitignored 不入库）
- 1.5B 专家（`experts_15b/`)、自动门产出（`data_auto*/`)、CMMLU(`data_bench/`）不入库，用上面的命令复现

## 局限（明示）

专家**只增不改**：更新/删除记忆需要重训或淘汰机制（未做）；事实需以问答对形式写入，陈述句→问题的自动转换未做；自答信号存在"瞎猜猜中"的理论风险（250 条未观测到）；真 MoE 层内路由（OLMoE 式）是下一步方向，未实现。

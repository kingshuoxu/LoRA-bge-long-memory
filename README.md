# LLM 参数化长记忆实验:LoRA 专家池 + 检索式门控路由

验证一个问题:**LLM 能否把经验写进可插拔的"专家"参数块,实现不占 prompt、可选择性读取、且不遗忘的长记忆?**

结论(2026-07-31,5 专家 × 50 条虚构事实):

| 假设 | 指标 | 结果 | 判定 |
|---|---|---|---|
| H1 可写入 | 记忆准确率 | 均值 **93.6%**(82%~100%) | 成立 |
| H2 可选择性读取 | 常识问题误激活率 | **0%**(20/20) | 成立 |
| H3 不遗忘 | 批次 0 经历 4 轮后续写入后的保持率 | **88% → 88%** | 成立 |

不遗忘是架构的结构性属性:每批记忆是一个物理隔离的 LoRA 文件(~51MB),不在后续训练的梯度路径上。删掉文件 = 精确遗忘该批知识。

## 原理

```
新经验(一批事实) ──训练──> LoRA 专家 E_k(冻结基座,只训 FFN 上的 adapter)
                                │
提问 ──bge 编码──> 与各专家的事实级路由键算 max 余弦相似度
                                │
                    sim ≥ τ(0.5)? ──否──> 用纯基座回答
                                │是
                        激活对应 LoRA 专家作答
```

- 基座:Qwen2.5-0.5B-Instruct(冻结);专家:LoRA r=32,挂在每层 FFN(gate/up/down)
- 路由:bge-small-zh-v1.5,每条事实一个向量,检索式 max-sim(LLM 隐向量实测无区分度,见下文)
- 训练:CPU(DirectML 前向有数值偏差,不可训练);推理:GPU(torch-directml)

## 复现

```bash
# 环境:Python 3.12(注意:不支持 3.13,torch-directml 无 cp313 wheel)
py -3.12 -m venv .venv
.venv/Scripts/pip install torch-directml transformers==4.45.2 peft==0.13.2 accelerate==0.34.2 modelscope

# 下载模型(国内源)
.venv/Scripts/python -c "from modelscope import snapshot_download; snapshot_download('Qwen/Qwen2.5-0.5B-Instruct', local_dir='models/Qwen2.5-0.5B-Instruct')"
.venv/Scripts/python -c "from modelscope import snapshot_download; snapshot_download('AI-ModelScope/bge-small-zh-v1.5', local_dir='models/bge-small-zh-v1.5')"

# 1. 生成虚构事实数据(5 批 × 50 条 + 20 常识问题)
.venv/Scripts/python scripts/gen_data.py

# 2. 训练专家(CPU,每批约 20~30 分钟)
.venv/Scripts/python scripts/train_expert.py --batch 0 --cpu

# 3. 评估(记忆准确率 + 选择性;--sweep 可看路由相似度分布)
.venv/Scripts/python scripts/eval_memory.py --tau 0.5
```

## 仓库结构

```
scripts/            主流程
  gen_data.py       虚构事实生成器(保证基座不可能见过,避免"本来就知道"污染)
  base_sanity.py    基座 sanity check(G4 基线 + 上下文 QA 能力)
  train_expert.py   写入:LoRA 专家训练(QA 格式 + 位置选择性 loss)+ 路由键生成
  eval_memory.py    读取:bge 门控路由 + 记忆/选择性评估
  router.py         bge embedding 封装
  smoke_directml.py DirectML smoke test
  debug/            排障期诊断脚本(梯度流/优化器/算子 profiling,复现 §排障记录)
docs/
  experiment-design.md   实验设计(假设、分组、指标、风险)
  experiment-results.md  结果、失败模式、"晚期发散"发现
papers/             文献笔记(gitignore,不入库)
data/               虚构事实数据(已入库,也可用 gen_data.py 再生)
experts/            训练好的 5 个 LoRA 专家 + 路由表(已入库,~256MB,可重训再生)
models/             基座与 embedding 模型权重(gitignore,按 README 命令下载)
```

## 关键失败模式(排障记录摘要)

1. **torch-directml 可推理不可训练**:fp32/fp16 前向与 CPU 偏离(初始 loss 20.7 vs 3.09),训练改用 CPU;
2. **LLM 中间层隐向量不能做路由键**:任意文本余弦 ≥0.999(各向异性),改独立 embedding 模型;
3. **陈述句训练 ≠ 问答能力**:训练数据必须包含 chat 格式 QA 对;
4. **LoRA 记忆的"晚期发散"**:收敛后继续训练会擦除刚写入的记忆 → 早停是记忆生命周期管理的一部分。

详见 `docs/experiment-results.md`。

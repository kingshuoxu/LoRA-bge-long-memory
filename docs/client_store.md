# 客户端记忆目录

手机应用「长期记忆」和仓库里的 `experts/` 用同一套事实文件。桌面客户端那条线在写这份说明时还没有提交自己的目录格式,所以这里按仓库已经在用的字段定一份两边都能读的约定。多出来的字段都是附加的,旧脚本不认识也可以跳过。

根目录在手机上是应用私有目录里的 `memory/`。仓库里对应的是 `experts/` 加上各批事实。两边不要互相覆盖:仓库继续放 PEFT 的 `adapter_model.safetensors` 和 `router_key.pt`,手机读的是导出的 GGUF 和 float32。

## router.jsonl

每行一个专家,和现在的 `experts/router.jsonl` 一样:

| 字段 | 含义 |
|---|---|
| `expert` | 目录名,例如 `expert_0` |
| `batch` | 批次号,删除后按这个排序写回 |
| `n_facts` | 这条专家里的事实条数 |
| `rank` | LoRA rank,仓库是 32 |
| `key_path` | 路由键。仓库是 `router_key.pt`(torch),手机是同目录的 `router_key.f32` |

手机多写三个字段,桌面端可以忽略:

| 字段 | 含义 |
|---|---|
| `weight` | GGUF LoRA 的相对路径,`experts/<name>/adapter.gguf` |
| `key_format` | `float32`。有这个字段就不要 `torch.load` |
| `dim` | 512,bge-small-zh-v1.5 的维度 |

`router_key.f32` 是一行一个键、每个键 512 个 little-endian float32,没有文件头。读法是 `np.fromfile(path, dtype="<f4").reshape(-1, 512)`,再按行做和 PyTorch 一样的 L2 归一化结果(导出时已经归过一)。`torch.load` 读不了这个文件。

## 专家目录

`experts/<name>/` 里和仓库对齐的文件:

- `fact_memory.json`:数组。每条有 `entity`、`value`、`statement`、`questions`(字符串数组)。没有 `attr`。和 `write_fact_memory` 写出来的一样。
- `key_texts.json`:字符串数组。第一条是陈述句,后面是问句,顺序和训练时的路由键一致。
- `adapter_config.json`:保留 PEFT 的 `peft_type=LORA`、`r`、`lora_alpha`、`target_modules`(gate_proj / up_proj / down_proj)。手机额外写 `weight_file=adapter.gguf`、`weight_format=gguf-lora`。

手机额外有:

- `adapter.gguf`:llama.cpp / QVAC 的 f16 LoRA。
- `router_key.f32`:这个专家的路由键。
- `fact_vectors.f32`:事实闸向量,行数是每条事实的 `1 + len(questions)`,顺序和 `load_fact_memory` 拼起来的顺序一样。

`experts/fact_gate.json` 继续用仓库的阈值:`tau` 0.622,`mask`「某」,`value_mask`「某值」,`use_paraphrases` 和 `use_reranker` 都是 false。

## 对话

手机把一次聊天存成 `conversations/<id>.json`:

```json
{
  "id": "c-ab12cd34",
  "title": "新对话",
  "created": "2026-10-22T00:00:00Z",
  "updated": "2026-10-22T00:00:00Z",
  "messages": [
    {"role": "user", "content": "……"},
    {"role": "assistant", "content": "……", "expert": "expert_0", "reason": "entity"}
  ]
}
```

`expert` 和 `reason` 只出现在助手消息上,表示这条回答挂了哪个专家、路由为什么开火。桌面端若要做同一套整理流程,选中的对话 id 会写进待训练事实的 `sources`。

## 训练任务

整理页确认之后写 `train/job.json`:`expert`、`rank` 32、`lr` `5e-4`、`epochs` 4、`facts`。每条事实有 `entity`、`statement`、`value`、`qa`(`q`/`a`)。送给训练程序的是 `train/facts.jsonl`,每行一条 `statement` 加 `qa`。陈述句整句算 loss,QA 只在答案上算 loss,和 `scripts/train_expert.py` 的 `FactDataset` 一致。命令是微批 1、`--grad_accum_steps 8`,这样一次 Adam 更新对着 8 条样本,又不必把 8 条同时放进内存。适配器写到 `train/<expert>.gguf`,检查点在 `train/mft/`。

QVAC b7349 固定把末尾约 5% 当验证,没有开关。`MemoryStore.tailCount` 会把开头若干行再接到末尾,让每一条原始样本都落在训练切分里。

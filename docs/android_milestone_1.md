# 安卓第一期:桌面核对与小米 15

目标机是小米 15,骁龙 8 Elite,Adreno 830,arm64。这一期先在桌面把转换、路由和 QVAC 能不能训 Qwen2 核对完,再在上面做可安装的 APK。安装步骤在 `android/README.md`,目录约定在 `docs/client_store.md`。

## 桌面已经核对

对照都在 x86_64 桌面上做,用的是 QVAC 源码标签 b7349(提交 `b73e75af5f2ab69c0e8984637c743c6a50ebc98d`)编出来的 `llama-cli` / `llama-embedding` / `llama-finetune-lora`。生成是贪心:`--temp 0 --top-k 1 --top-p 1 --min-p 0 --seed 0`。命中规则和 `scripts/eval_memory.py` 相同,`gold.rstrip("年")` 出现在回答里。问句后面加「请简短回答。」,system 是「你是助手。」。

| 项目 | 结果 |
|---|---|
| 官方 Qwen2.5-0.5B-Instruct Q8_0 + expert_0 的 f16 LoRA | **45/50**。错的五条都是产品编号:b0-022 温巴希克-373→格克尔-771,b0-026 格索姆-667→格索姆-670,b0-030 辛达菲萨-873→菲希菲克-894,b0-031 克洛佩雷-830→克洛雷-830,b0-049 布纳辛-470→布纳德-870 |
| 本地 f16 基座 + 同一份 LoRA | **50/50** |
| bge GGUF,均值池化 + L2,文本里没有大写拉丁字母 | 余弦 min 0.999998,8869 条 |
| bge GGUF,文本里有大写字母(主要是 CEO) | 余弦可以掉到 0.845。llama.cpp 的 WordPiece 会把拉丁字母转成小写,这个分词器 `do_lower_case` 是 false |
| llama.cpp 问句向量 + PyTorch 路由键,11687 条 | **11687/11687** 和 `scripts/router.py` 的决定一致。大写字母的余弦差没有改路由 |
| C++ 路由的字符串逻辑(相似度 0.99 / 0 / 拉开差距 / 删掉 expert_4) | 和 Python 一致,同一批 11687 条 |
| QVAC 能否加载 Qwen2 并做 LoRA 反向传播 | 能。`general.architecture=qwen2` 的 Q8_0 跑过前向和反向 |

bge 转换钉在 llama.cpp b7349(`4df6e859e92dac52536f735785bb9e0a3bc63e2b`)。b7349 不认识 bge-small-zh-v1.5 的分词器指纹 `56a3532a4cda32cf10d09834e0cdeee45c407d750b868651e44e2eebdcc721ed`,`convert_bge.sh` 把它补成和英文 bge 相同的 `bert-bge`。空的 `sentencepiece.bpe.model` 要删掉,否则转换器会把模型认成 BPE。

路由程序是 `android/router/memory_route.cpp`。实体优先、边界守卫、bge 的 τ=0.6、事实闸 τ=0.622、掩码「某」、值掩码「某值」,和 `fact_gate.json` 里 `use_paraphrases` / `use_reranker` 都关闭的设定一致。

### 事实闸

PyTorch 的问句向量和掩码向量喂给 C++ 做点积和阈值,问句集合和上面相同。`android/scripts/verify_router.py --full` 的结果是 **11687/11687** 一致,五个专家的实体名单成员也和 Python 一致。带 CEO 的问句没有把事实闸打偏,所以没有改走 ONNX。

### 训练探针(没有 12 epoch 的准确率)

QVAC 这一版一次一步、没有微批,`--assistant-loss-only` 吃 ChatML JSONL。loss 是助手 token 上的全词表平均交叉熵,不是仓库 `selective_loss` 那种只回传被监督 token 的做法。`val_split` 写死 0.05,命令行不认 `--val-split`。没有看到梯度裁剪开关。检查点可以用 `--checkpoint-save-steps`、`--resume-from`、`--auto-resume`。

| 学习率 | 发生了什么 |
|---|---|
| 5e-4(仓库的值,40 条小样本,rank 8) | 15 步里 loss 从 5.17 升到 6.11,准确率往下走。进程被停掉,没有跑完 |
| 1e-4,batch_0,rank 32,Q8 基座 | 到第 99 步 loss 约 12.1,准确率掉到约 9%。第 50 步写出过检查点 `checkpoint_step_00000050/model.gguf`,说明存盘是通的 |
| 2e-5,同一批,rank 32 | 前 30 步 loss 停在 6.8 附近,没有爆。第 30 步时进程被停掉(退出码 147),没有适配器,也没有记忆准确率 |

所以 Qwen2 不是「架构不支持」。对不上的是学习率:仓库的 5e-4 靠的是选择性 loss,QVAC 的全词表 loss 吃不住。应用和手机脚本默认 2e-5、rank 32、alpha 64、模块 `ffn_gate,ffn_up,ffn_down`、12 epoch、AdamW、weight decay 0。**没有** QVAC 训出来的专家达到 48/50。这一步要在小米 15 上把 12 个 epoch 跑完,再用 f16 基座按 `verify_memory_gguf.py` 的规则去对。没有因此去改 Qwen3-0.6B 或 ONNX Runtime:前向和反向已经在 Qwen2 上跑通,剩下的是学习率和时长,不是换架构。

陈述句在仓库里是整句 loss,QA 只在答案上。QVAC 一次运行只能开一种 assistant-only,`prepare_train_jsonl.py` 把陈述句包成「请记下这句话。」,让两类样本进同一次训练。这和 `FactDataset` 不是同一条 loss,差在这里。

桌面 4 核上,2e-5 的探针大约 3 秒一步,一个 epoch 约 24 分钟。12 个 epoch 量级是数小时,还没算手机上的热降频。

## arm64 冒烟(不是手机)

`android/router/memory-route-aarch64` 是 Linux 静态二进制,在 x86_64 上用 `qemu-aarch64-static` 跑过一条实体路由:问「塔佐巴洛公司的总部在哪里?」,输出 `expert_0`、`fired=true`、`reason=entity`。这只说明同一份 C++ 在 arm64 指令下还能做实体优先,不是安卓 bionic,也不是 APK。

APK 里的 `libmemoryroute.so` 另有一条仪器测试 `RouterSmokeTest`,要装到 arm64 模拟器或真机上才执行。模拟器结果见文末。

## 模拟器

本机有 `/dev/kvm`,也装了 Android Emulator 37.2.12.0 和 `system-images;android-35;aosp_atd;arm64-v8a`。创建 AVD 之后启动被拒绝:

```
FATAL | Avd's CPU Architecture 'arm64' is not supported by the QEMU2 emulator on x86_64 host.
System image must match the host architecture.
```

这版模拟器不在 x86_64 上翻译 arm64 客户机,KVM 也不能跑另一种指令集。仪器测试 `RouterSmokeTest` 已经能编进 `assembleDebugAndroidTest`,但没有设备可以装。APK 本身因此没有在模拟器里安装、启动或点过。对话、Vulkan、训练时长都要真机。

## 必须在小米 15 上做的

- 插入 f16 基座后,用应用问 batch_0 的第一问,确认还是 50/50 里的那种回答,尤其是上面五条产品编号。
- 专家页打开 Vulkan 再问一句,确认 Adreno 830 上 `-ngl 99` 能出字。失败就拨回 CPU。
- 插电、熄屏,或勾选立即训练,把一条审过的事实训完 12 个 epoch。看通知、`telemetry.tsv`(RSS、热区、电量)、检查点能不能续上、取消能不能停。
- 训完开新对话,确认新专家被挂上;删掉之后不再挂。
- 用 Termux 路径时,对一下 `telemetry.log` 里的 RSS 是不是训练进程,而不是采样脚本自己。

这些桌面和模拟器都代替不了。

## CI

工作流 `.github/workflows/android-apk.yml`,名字 `Android APK`。在 `android/**` 或该工作流文件的 push / pull request 上跑。步骤是装 SDK 35、NDK `27.2.12479018`、CMake 3.22.1,下载上面那个 Adreno zip 并校验 sha256,然后 `./gradlew testDebugUnitTest assembleDebug assembleDebugAndroidTest`。产物名 **`lorabge-memory-arm64-debug`**,里面是签名调试 APK `app-debug.apk`。调试签名是 Android Gradle 的默认 debug keystore,不是上架用的发布签名。

模拟器没有放进 CI,arm64 镜像在 x86 宿主上是指令翻译,容易超时。

这次运行的 URL 写在文末和 PR 描述里。

## 阻塞

1. **QVAC 全词表 loss 吃不住仓库的学习率。** Qwen2 能训,5e-4 和 1e-4 发散,2e-5 只看了 30 步。没有 12 epoch、没有 ≥48/50 的 QVAC 适配器。
2. **bge 的大写拉丁字母。** 纯中文余弦是 1.0;带 CEO 这类大写时 llama.cpp 会小写化。用 PyTorch 键、llama 问句时,11687 条路由没有因此改判。事实闸是否改判见文末。没有改走 ONNX。
3. **手机命令行和桌面 b7349 不是同一次构建。** 手机包短提交 `29fe08c`,完整哈希在 ggml-org/llama.cpp、tetherto/qvac-fabric-llm.cpp、qvac-fabric-llm-finetune 上都没有对上。桌面能用的旗标不要假设手机二进制全都认;`--val-split` 在桌面 b7349 上会被拒绝。
4. **桌面客户端还没有提交目录格式。** 应用按本文和 `docs/client_store.md` 实现。JSON 字段跟仓库的 `router.jsonl` / `fact_memory.json` 对齐,GGUF 和 float32 是附加文件。
5. **官方模拟器拒绝在这台 x86_64 上启动 arm64 镜像。** 见上面的 FATAL。APK 冒烟要等小米 15,或者一台本身就是 arm64 的模拟器宿主。

## 核对记录

- 逻辑路由四种情形 11687/11687,事实闸 11687/11687,实体抽取 5 个专家名单一致。
- `export_phone_bundle.py` 写出 5 个专家、事实向量 2250 行。这个目录在 `android/out/`,不入库。
- `qemu-aarch64-static` 跑静态 arm64 路由:实体问句挂上 `expert_0`,理由 `entity`。
- 本地 `./gradlew testDebugUnitTest assembleDebug assembleDebugAndroidTest` 通过。`MemoryStoreTest` 3 项 0 失败。签名调试 APK 只含 arm64-v8a,里面有 `libmemoryroute.so`、三条 QVAC 命令(改名为 `libllama-*.so`)和 ggml / vulkan 的 so。
- 模拟器没有把这个 APK 装上去,原因见上一节。
- CI 运行 URL 在 PR 描述里。产物名 `lorabge-memory-arm64-debug`。

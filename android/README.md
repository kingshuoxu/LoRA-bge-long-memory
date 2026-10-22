# 长期记忆(小米 15)

安装包只含 arm64。包名 `com.lorabge.memory`,界面三个页:对话、整理、专家。对话走实体优先、边界守卫、bge 相似度和事实闸;整理页把勾选的对话收成审过的事实,再在后台训一个新的 LoRA;专家页可以导入、自检、切换 CPU/GPU、删除。目录格式见 `docs/client_store.md`。桌面上已经对过的数字和还没在真机上做的事见 `docs/android_milestone_1.md`。

## 电脑上先准备

```bash
git lfs pull --include "experts/**"
sh android/scripts/fetch_base_gguf.sh          # 官方 Q8_0,训练用
sh android/scripts/convert_base.sh             # f16 基座,对话 50/50 用这份
python android/scripts/convert_experts.py      # PEFT → GGUF LoRA
sh android/scripts/convert_bge.sh              # bge-small-zh-v1.5 f16
python android/scripts/export_phone_bundle.py  # 路由键、事实向量、router.jsonl
```

`convert_bge.sh` 和 `convert_experts.py` 把转换器钉在 ggml-org/llama.cpp 标签 b7349,提交 `4df6e859e92dac52536f735785bb9e0a3bc63e2b`。bge 转换会给 b7349 补上 bge-small-zh-v1.5 的分词器指纹,推理必须 `--pooling mean --embd-normalize 2 -c 128`。

APK 里的命令行来自 QVAC 的 Adreno arm64 包,不是 b7349 那个只含 `libllama-android.so` 的压缩包。

```bash
cd android/apk
sh download_qvac.sh    # sha256 3a09dad897f97b85c87374c7b40d1c51377a900c5a3f88e60c9d4059fc758b32
./gradlew assembleDebug
```

签名调试包在 `android/apk/app/build/outputs/apk/debug/app-debug.apk`。GitHub Actions 工作流 `Android APK` 也会打出同名产物 `lorabge-memory-arm64-debug`。

## 装到小米 15

手机开开发者选项和 USB 调试,数据线连上电脑,`adb devices` 能看到设备。然后:

```bash
sh android/phone/push_adb.sh
```

脚本会安装 APK,并推到 `/sdcard/Android/data/com.lorabge.memory/files/`:

| 手机上的文件 | 来源 | 用途 |
|---|---|---|
| `models/base.gguf` | f16 基座 | 对话。Q8_0 在 batch_0 上是 45/50,f16 是 50/50 |
| `models/Qwen2.5-0.5B-Instruct/` | safetensors + 词表 | 只给训练。进内存后按 fp32 做反向 |
| `models/bge.gguf` | bge f16 | 路由 |
| `import/router.jsonl` 和 `import/expert_*/` | `export_phone_bundle.py` | 已有五个专家 |

打开「长期记忆」。专家页点「导入已推送的专家」,再点「路由自检」,应显示「路由自检通过: entity」。

## 在手机上试

1. 对话页新建对话,问「塔佐巴洛公司是哪一年成立的?」。挂上 `expert_0`、理由是实体,回答里有 1978。这五条在 Q8 上会错、在 f16 上桌面已经对过:b0-022、b0-026、b0-030、b0-031、b0-049,都是产品编号。
2. 再问一句和库无关的话,不应挂专家。
3. 整理页勾选刚才的对话,填实体、陈述句、答案、问句。想马上训就勾「立即训练」。不勾的话要插着电,并且把屏幕关掉,训练才会开始。
4. 通知栏能看到进度。`train/status.json` 是状态,`train/telemetry.tsv` 是耗时、RSS、热区、电量,`train/mft/` 是检查点。点「取消训练」会停掉进程。训练读的是 `models/Qwen2.5-0.5B-Instruct/`(safetensors、config、词表),不是 GGUF。
5. 训完专家页出现新的 `expert_`,再开一个新对话,问刚才写入的那句,应挂到这个新专家。
6. 点删除,索引会重写,再问这句不应再挂它。

专家页的「切换 CPU / GPU」管对话。默认 CPU(`-ngl 0`)。小米 15 的 Adreno 830 可以改成 Vulkan(`-ngl 99`)。Vulkan 起不来就拨回 CPU。训练始终在 CPU 上。

训练用 APK 里的 `libtrain-mft.so`(MobileFineTuner,FFN LoRA,学习率 5e-4,4 个 epoch)。桌面上同一份程序把 batch_0 训到第 4 个 epoch 是 48/50;第 12 个 epoch 掉到 22/50。对话和向量仍是 QVAC 的 `llama-cli` / `llama-embedding`。`llama-finetune-lora` 不再被调用:它的梯度和 PyTorch 对不上。

## 不装 APK,只用 Termux

训练程序用 `android/trainer/build_android.sh` 编出来的 `train_wikitext`。第一个参数是 Hugging Face 模型目录,第二个是 `facts.jsonl`(每行 `statement` 和 `qa`),第三个是输出目录。

```bash
sh android/phone/termux_train.sh /path/to/Qwen2.5-0.5B-Instruct /path/to/facts.jsonl /path/to/out
```

遥测写到 `out/telemetry.log`,采样的是训练进程的 VmRSS / VmHWM,加上 `/sys/class/thermal/thermal_zone*` 和电池电量,10 秒一次。

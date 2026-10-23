# 长期记忆(小米 15)

安装包只含 arm64。包名 `com.lorabge.memory`。界面是深空底:对话、巩固、星云、记忆库,可以切中文和英文。对话走实体优先、边界守卫、bge 相似度和事实闸。要改一条记忆,直接说出新事实,确认之后会重新训练。巩固页把确认过的事实按桌面同一套问法展开再训;星云按专家和事实画,上次路由到的专家会亮。训练时背景动画停住。目录格式见 `docs/client_store.md`。数字见 `docs/android_milestone_1.md`。

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

对话和嵌入用的 `libllama.so` 从 QVAC 提交 `b73e75af5` 交叉编译,并打上 `android/qvac/wpm-cased.patch`,这样 bge 的大写词不会被折成小写。编译优先打开 Vulkan,给小米 15 的 Adreno 830 用;着色器工具链失败才退回 CPU。训练程序另外链一份 OpenBLAS ARMv8。

```bash
sh android/trainer/build_android.sh   # OpenBLAS ARMv8 + libtrain-mft.so
sh android/qvac/build_android.sh      # libllama.so、llama-cli、llama-embedding
cd android/apk && ./gradlew assembleDebug
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

打开「长期记忆」。记忆库点「导入已推送的专家」,再点「路由自检」,应显示「路由自检通过: entity」。

## 在手机上试

1. 对话页新建对话,问「塔佐巴洛公司是哪一年成立的?」。挂上 `expert_0`、理由是实体,回答里有 1978。这五条在 Q8 上会错、在 f16 上桌面已经对过:b0-022、b0-026、b0-030、b0-031、b0-049,都是产品编号。
2. 再问一句和库无关的话,不应挂专家。
3. 巩固页填实体、陈述句、取值和确认过的问句。想马上训就勾「立即训练」。不勾的话要插着电,并且把屏幕关掉,训练才会开始。对话里说「不对,……是……」会先弹出确认,确认后按这条新事实重训。用户确认过的事实一定训练,哪怕闸门本来想跳过。
4. 通知栏能看到进度。`train/status.json` 是状态,`train/telemetry.tsv` 是耗时、RSS、热区、电量,`train/mft/` 是检查点。点「取消训练」会停掉进程。训练读的是 `models/Qwen2.5-0.5B-Instruct/`(safetensors、config、词表),不是 GGUF。
5. 训完,记忆库和星云里出现新的 `expert_`。再开一个新对话,问刚才写入的那句,应挂到这个新专家。
6. 点删除,索引会重写,再问这句不应再挂它。

记忆库的「切换 CPU / GPU」管对话。默认 CPU(`-ngl 0`)。小米 15 的 Adreno 830 走 Vulkan(`-ngl 99`,`libggml-vulkan.so`)。Vulkan 起不来就拨回 CPU。训练始终在 CPU 上,GEMM 是 OpenBLAS ARMv8。

训练用 APK 里的 `libtrain-mft.so`(MobileFineTuner,FFN LoRA,OpenBLAS ARMv8,学习率 5e-4,4 个 epoch,微批 1、梯度累加 8)。研究批次 `batch_0` 在桌面上按这个更新规则跑完是 49/50。应用里一次巩固大约是 4 条事实、32 条样本、每个 epoch 4 步;这台 Xeon 上大约 7 分钟,原问 4/4,留出复述 4/4,没写过的问题 2/2 弃权。真机用:

```bash
sh android/phone/run_device_benchmark.sh
```

脚本安装 APK,把本机的 safetensors、f16 基座和 bge 推进调试包的私有目录,跑完打印墙钟、峰值 RSS、热区温度和三项回忆。把输出贴回来即可。对话和向量是 QVAC `b73e75af5` 加大小写补丁编出来的 `llama-cli` / `llama-embedding`。`llama-finetune-lora` 不再放进 APK:它的梯度和 PyTorch 对不上。

## 不装 APK,只用 Termux

训练程序用 `android/trainer/build_android.sh` 编出来的 `train_wikitext`。第一个参数是 Hugging Face 模型目录,第二个是 `facts.jsonl`(每行 `statement` 和 `qa`),第三个是输出目录。

```bash
sh android/phone/termux_train.sh /path/to/Qwen2.5-0.5B-Instruct /path/to/facts.jsonl /path/to/out
```

遥测写到 `out/telemetry.log`,采样的是训练进程的 VmRSS / VmHWM,加上 `/sys/class/thermal/thermal_zone*` 和电池电量,10 秒一次。

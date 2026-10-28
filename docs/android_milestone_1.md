# 安卓第一期:桌面核对与小米 15

目标机是小米 15,骁龙 8 Elite,Adreno 830,arm64。这一期先在桌面把转换、路由和 QVAC 能不能训 Qwen2 核对完,再在上面做可安装的 APK。安装步骤在 `android/README.md`,目录约定在 `docs/client_store.md`。

## 桌面已经核对

对照都在 x86_64 桌面上做,用的是 QVAC 源码标签 b7349(提交 `b73e75af5f2ab69c0e8984637c743c6a50ebc98d`)编出来的 `llama-cli` / `llama-embedding` / `llama-finetune-lora`。生成是贪心:`--temp 0 --top-k 1 --top-p 1 --min-p 0 --seed 0`。命中规则和 `scripts/eval_memory.py` 相同,`gold.rstrip("年")` 出现在回答里。问句后面加「请简短回答。」,system 是「你是助手。」。

| 项目 | 结果 |
|---|---|
| 官方 Qwen2.5-0.5B-Instruct Q8_0 + expert_0 的 f16 LoRA | **45/50**。错的五条都是产品编号:b0-022 温巴希克-373→格克尔-771,b0-026 格索姆-667→格索姆-670,b0-030 辛达菲萨-873→菲希菲克-894,b0-031 克洛佩雷-830→克洛雷-830,b0-049 布纳辛-470→布纳德-870 |
| 本地 f16 基座 + 同一份 LoRA | **50/50** |
| bge GGUF,均值池化 + L2,文本里没有大写拉丁字母 | 余弦 min 0.999998,8869 条 |
| bge,带大写拉丁字母,桌面 QVAC 嵌入器 | 12 条最低余弦 **0.999998**。`CEO` 编成 `[CLS] [UNK] [SEP]`,和 `do_lower_case=false` 一致 |
| bge,APK 里的 `libllama.so` | 从 QVAC `b73e75af5` 加 `android/qvac/wpm-cased.patch` 交叉编译。`tokenize` 对 pre 做长度 14 的比较,两个立即数拼成 `bert-bge-cased`,相等时不做小写。编译器把这 14 个字节折进指令,`.so` 里没有连续的那串字符。后端是 Vulkan:`libggml-vulkan.so` 依赖系统 `libvulkan.so`,给 Adreno。不是 OpenCL,也不是旧的 `29fe08c` zip |
| llama.cpp 问句向量 + PyTorch 路由键,11687 条 | **11687/11687** 和 `scripts/router.py` 的决定一致。这是小写化还在的时候量的,大写余弦差没有改判 |
| C++ 路由的字符串逻辑(相似度 0.99 / 0 / 拉开差距 / 删掉 expert_4) | 和 Python 一致,同一批 11687 条 |
| QVAC 能否加载 Qwen2 并做 LoRA 反向传播 | 能。`general.architecture=qwen2` 的 Q8_0 跑过前向和反向 |

bge 转换钉在 llama.cpp b7349(`4df6e859e92dac52536f735785bb9e0a3bc63e2b`)。b7349 不认识 bge-small-zh-v1.5 的分词器指纹 `56a3532a4cda32cf10d09834e0cdeee45c407d750b868651e44e2eebdcc721ed`,`convert_bge.sh` 把 GGUF 的 `tokenizer.ggml.pre` 写成 `bert-bge-cased`。空的 `sentencepiece.bpe.model` 要删掉,否则转换器会把模型认成 BPE。b7349 自己的 WPM 不看这个 pre 字符串,默认仍把码点转成小写。桌面能对上 PyTorch 的那个 `llama-embedding` 来自 QVAC 提交 `b73e75af5`,另外加了一段本地补丁:只有 pre 是 `bert-bge-cased` 时不做小写。2026-10-22 重新量过 12 条,含 `CEO`、`NASA`、`iPhone`、`Beijing`。和 PyTorch mean-pool + L2 的余弦最低 0.999998,最高也在 0.999999。`The CEO of the company lives in Beijing.` 和全小写那句,PyTorch 自己的余弦是 0.836,这就是以前写的「可以掉到 0.845」。llama 对大小写原文仍是 0.999999。`CEO` 的 id 是 100(`UNK`),`ceo` 是 8371。旧 zip(`29fe08c`,sha256 `3a09dad897f97b85c87374c7b40d1c51377a900c5a3f88e60c9d4059fc758b32`)里搜不到 `bert-bge-cased`,只改 GGUF 元数据修不到手机。现在这份 `libllama.so` 在 `tokenize` 里用立即数比较 `bert-bge`(`0x6567622d74726562`)和 `ge-cased`(`0x64657361632d6567`),长度先比 14,不相等才把 `do_lower=true` 传给 `preprocess(text, bool)`。反汇编对得上补丁。LOAD 对齐 `0x4000`。

路由程序是 `android/router/memory_route.cpp`。实体优先、边界守卫、bge 的 τ=0.6、事实闸 τ=0.622、掩码「某」、值掩码「某值」,和 `fact_gate.json` 里 `use_paraphrases` / `use_reranker` 都关闭的设定一致。

### 事实闸

PyTorch 的问句向量和掩码向量喂给 C++ 做点积和阈值,问句集合和上面相同。`android/scripts/verify_router.py --full` 的结果是 **11687/11687** 一致,五个专家的实体名单成员也和 Python 一致。带 CEO 的问句没有把事实闸打偏,所以没有改走 ONNX。

### 训练

QVAC 这一版一次一步、没有微批,`--assistant-loss-only` 吃 ChatML JSONL。loss 是助手 token 上的全词表平均交叉熵,不是仓库 `selective_loss` 那种只回传被监督 token 的做法。`val_split` 写死 0.05,命令行不认 `--val-split`。没有看到梯度裁剪开关。检查点可以用 `--checkpoint-save-steps`、`--resume-from`、`--auto-resume`。

| 学习率 | 发生了什么 |
|---|---|
| 5e-4(仓库的值,40 条小样本,rank 8) | 15 步里 loss 从 5.17 升到 6.11,准确率往下走。进程被停掉,没有跑完 |
| 1e-4,batch_0,rank 32,Q8 基座 | 到第 99 步 loss 约 12.1,准确率掉到约 9%。第 50 步写出过检查点 `checkpoint_step_00000050/model.gguf`,说明存盘是通的 |
| 2e-5,同一批,rank 32 | 前 30 步 loss 停在 6.8 附近,没有爆。第 30 步时进程被停掉(退出码 147),没有适配器,也没有记忆准确率 |

QVAC 的反向和 PyTorch 对不上。同一条序列上,24 层 LoRA 梯度的余弦大约是 -0.03,前面几层的梯度范数比 PyTorch 大几十倍。Adam 和 SGD 都会停在初始 loss,或者把 loss 越训越高。这不是学习率能修的。

训练改走 MobileFineTuner 的 Qwen2.5-0.5B 原生自动微分,提交 `086b1a027fe708d5eaca89b1ec2bf1a876fb80de`,补丁在 `android/trainer/mft-ffn-lora.patch`。补丁加了 FFN 的 gate/up/down LoRA,loss 只算 JSONL 掩码标出来的 token,和仓库 `selective_loss` 一样是移位后的交叉熵。单条事实可以在几步里从 4.7 收到 0.0001。配方是 rank 32、alpha 64、Adam、学习率 5e-4、weight decay 0、梯度裁剪 1.0、batch 8、seed 42。基座在内存里用 fp32,这样 GEMM 走 BLAS;对话仍用 f16 GGUF。手机上的 `libtrain-mft.so` 和桌面这个二进制是同一份源码,并且都链 OpenBLAS。手机这份是 OpenBLAS 0.3.28、`TARGET=ARMV8`(NEON,不用 SVE)、`NO_AFFINITY=1`,编译期最多 8 线程。交叉编译时 `uname` 是 Linux,OpenBLAS 会自己打开 `sched_setaffinity`。vivo X200 Pro 上第一次 `cblas_sgemm` 因此不返回,巩固停在 `[Dataset] epochs=4 max_steps=8`,界面是「这一步还在计算 · 已过 2480 秒」。小米 15 的 8 个 Oryon 都是性能核,训练时把 `OPENBLAS_NUM_THREADS` 设成 `availableProcessors()` 和 8 里较小的那个。学习率、epoch、LoRA 目标和 loss 掩码是同一套。巩固时的样本格式也改成和桌面 `AssistantDataset` 一样:先问「请说出这条事实。」,每条确认过的问句再加「请简短回答。」,损失只在助手 token 上。闸门用的改写问句不进训练。

batch_0 的 450 条样本(50 条陈述句 + 每条 8 个 QA)跑了 12 个 epoch。每个 epoch 结束存一次权重,再用 f16 基座、`verify_memory_gguf.py` 的贪心规则打分。

| epoch | 该 epoch 平均 loss | 记忆 |
|---|---|---|
| 4 | 0.188 | **48/50** |
| 5 | 0.177 | 41/50 |
| 6 | 0.166 | 47/50 |
| 7 | 0.206 | 47/50 |
| 8 | 0.180 | 45/50 |
| 12 | 0.817 | 22/50 |

第 4 个 epoch 的两处未中:b0-000 标准答案 1978,生成 1979;b0-015 标准答案缪希希-565,生成缪希希-504。第 11、12 个 epoch 平均 loss 升到 0.55 和 0.82,答案开始重复字符,所以应用和脚本默认停在 4 个 epoch,不再跑满 12。

同一份第 4 个 epoch 的 fp32 权重,再用训练器自己的贪心解码打了一遍(safetensors 升到 fp32,不经过 f16 GGUF,`gen_new=12`,碰到 `151645` 停)。50 条里中了 **48** 条,错的还是这两题,答案也一样。训练和这条解码用的是同一种精度。f16 GGUF 对话链也是 48/50,错的是同两题。

这条 48/50 的优化轨迹是 **batch 8、OpenBLAS、4 核、seed 42、打乱**,一个 epoch 57 次更新。把 batch 改成 1、每次样本都更新(1800 次 Adam,学习率仍是 5e-4)时,第 1 个 epoch 的平均 loss 是 2.32,贪心解码 **0/50**,50 条答案都塌成 `-3-3-3` 这种重复。第 2 个 epoch 前 270 步的平均 loss 升到 3.06,没有往下走。纯 C++ 和 OpenBLAS 在 batch 1 的前三步上 loss 还对齐(4.07324、3.367、0.759),所以这不是 GEMM 舍入,是更新次数太多。

APK 和 Termux 因此改成 `--batch_size 1 --grad_accum_steps 8`:内存仍按一条样本走,每 8 条才做一次 Adam,一个 epoch 回到 57 次更新。和打出 48/50 的真 batch 8 仍有一点差别:梯度是 8 个「单条平均」再平均,不是 8 条放进同一个 batch 后按 token 加权。GEMM 两边都是 OpenBLAS,手机是 ARMv8 NEON。`libtrain-mft.so` 本来就认 `--grad_accum_steps`。

桌面上按这个调用(OpenBLAS,fp32 基座,4 个 epoch,228 步,6793 秒)再打了一次。四个 epoch 的平均 loss 是 1.375、0.251、0.228、0.181。第 4 个 epoch 的权重用训练器自己的贪心解码,基座仍是这份 fp32,**49/50**。未中的一条是 b0-044,标准答案菲希菲克-894,生成菲希塔希-894。同一份权重量化成 f16 GGUF,挂在本地 f16 基座上再用 `verify_memory_gguf.py` 打,也是 **49/50**,还是 b0-044,生成菲希塔-894。前三步 loss 是 5.06、4.58、2.96,真 batch 8 是 5.16、4.75、3.14。峰值 RSS 3.95 GB,稳态 2.62 GB。这 228 步还没有在手机上重跑。APK 的 GEMM 已经换成 OpenBLAS ARMv8,不再是纯 C++。

把第 4 个 epoch 的适配器强制挂在 20 条常识题上是 10/20,基座单独是 17/20。路由不会这么挂:这 20 句里没有 batch_0 的实体,和 50 条陈述句的 bge 余弦最高 0.429,低于 τ=0.6。对话走基座,常识题维持基座那一档。

陈述句在仓库里是整句 loss,QA 只在答案上。QVAC 一次运行只能开一种 assistant-only,`prepare_train_jsonl.py` 把陈述句包成「请记下这句话。」,让两类样本进同一次训练。这和 `FactDataset` 不是同一条 loss,差在这里。

桌面这台 4 核 Xeon 上,fp32、序列长 40,计时如下。骁龙 8 Elite 还没有墙钟数字。

| 路径 | 一步 | 4 个 epoch | 峰值内存 |
|---|---|---|---|
| batch 8,OpenBLAS,4 线程。这是打出 48/50 的那次 | 前 228 步平均 28.4 秒 | 6472 秒(1.80 小时) | 分配器峰值 5753 MB,稳态约 2102 MB |
| batch 1,OpenBLAS,4 线程。和 APK 的 batch、学习率、epoch 相同。这一行是 x86,APK 是 ARMv8 | 热身后大约 3.3 秒 | 1800 步,大约 1.6 小时 | 峰值 RSS 3.95 GB,稳态约 2.6 GB |
| batch 1,纯 C++ GEMM(`USE_BLAS=OFF`)。APK 以前的内核,这一行只作对照 | 第 2 步 11.9 秒,第 3 步 11.4 秒 | 若按 1800 次更新,在这台机器上大约 5.9 小时;累加 8 之后是 228 次更新 | 峰值 RSS 3.74 GB |
| batch 1、累加 8,OpenBLAS,4 线程。这是 APK 现在的更新次数 | 第 2 步 29.1 秒,第 3 步 29.0 秒 | 228 步,大约 1.8 小时 | 跑起来时 RSS 约 2.6 GB |
| 同一份源码,glibc aarch64 + OpenBLAS ARMv8,`qemu-aarch64-static`。只跑了不打乱的第 1 步 | 88.6 秒。这是用户态模拟,不是手机 | 没有跑完 450 行 | 权重加载后 RSS 约 2 GB |

x86 OpenBLAS 和这份 arm64 OpenBLAS 的第 1 步 loss 都是 **4.07324**,梯度 L2 都是 **1.00202**,差是 0,在 1e-3 里面。后两步 x86 是 3.3671、0.7591,和以前的纯 C++ 也对齐。qemu 的 88 秒不能当成小米 15 的一步。

### 巩固时真正会训的那一批

应用里一次巩固不是 450 行的 `batch_0`。桌面是抽出事实、按属性展开问法、用户确认的问句一定训练、改写只进事实闸。这里拿 `batch_0` 前 4 条(两家成立年份、两家总部),每条只把用户确认的第一问送进 `expand`,再加模板问法。训练程序再为每条加一行「请说出这条事实。」。

| 项目 | 数 |
|---|---|
| 事实 | 4 |
| 训练样本 | **32**(每条 1 句陈述 + 7 个问句) |
| 每个 epoch 的 Adam 步(微批 1、累加 8) | **4** |
| 4 个 epoch | **16** 步 |
| 这台 4 核 Xeon,OpenBLAS,前 10 步没被别的编译抢走 CPU | 一步大约 27 秒,16 步大约 **7 分钟** |
| 同一次实际墙钟(后几步和 libllama 编译抢 CPU) | **608 秒** |
| 原问回忆 | **4/4** |
| 留出的复述(没进训练,例如「是什么时候创办的」) | **4/4** |
| 从没写过的问题弃权 | **2/2**。`一年有多少个月?` 最高余弦 0.411,`法国的首都是哪里?` 0.351,都没有这四家实体,低于 τ=0.6 |

四个 epoch 的逐步 loss 从 5.35 收到 0.0009,中间有两步回到 0.22 和 0.12。贪心解码的原问和留出复述都答对了取值。弃权是路由,不是把 LoRA 强行挂上再生成。

小米 15 上的墙钟还没量到。纯 C++ 时,450 行研究批次在这台 Xeon 上要数小时;换成 OpenBLAS 之后,巩固这 32 条在这台机器上是几分钟。线程数按 cpufreq 只计大核和超大核:小米 15 两档 Oryon 是 8,天玑 9400 的 1+3+4 是 4。真机数字用 `android/phone/run_device_benchmark.sh`,它会装 APK、推模型、跑这 4 条事实,并打印墙钟、峰值 RSS、热区温度、SoC、GPU、后端和上面三项回忆。把整段输出贴回来即可。没有电脑时,设置里的「导出诊断」会打开分享。

对话和嵌入先试 Vulkan。短解码和一条 bge 嵌入要跟 CPU 一致,否则记住 CPU。Mali / Immortalis(厂商 0x13B5)另外关掉 coopmat 和 bf16,保留 fp16,tile 用真实子组宽度,并且只有短解码比 CPU 快才留在 GPU。Adreno 不看快慢。`libggml-cpu.so` 用 `armv8.7-a+dotprod+i8mm` 编译。强制 GPU / 强制 CPU 在记忆库里。导出的诊断里有两边的预填充和解码 tok/s,以及 Vulkan 设备名、驱动版本、子组宽度和特性。

只装 APK、没有电脑时,第一次打开会按清单自己下载。清单在预发布标签 `android-v0.1.0` 的 `manifest.json`,也打进了那次发布的 APK。镜像顺序是 ModelScope、hf-mirror.com、huggingface.co、GitHub Release。带大小写补丁的 bge 和五个专家只从这次发布的文件取。下载可以暂停,断了用 HTTP Range 续上,下完对 SHA256,空间不够会先停。下完会导入专家并做路由自检。

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
- 记忆库里点「切换 CPU / GPU」,再问一句,确认 Adreno 830 上 `-ngl 99` 能出字。失败就拨回 CPU。Vulkan 库是 `libggml-vulkan.so`。
- 插电、熄屏,或勾选立即训练,把审过的事实训完 4 个 epoch。也可以直接跑 `sh android/phone/run_device_benchmark.sh`,它会安装 APK、把 safetensors 和两个 GGUF 推进应用私有目录,并打印墙钟、峰值 RSS、温度和回忆。桌面上这 32 条样本大约 7 分钟,真机以脚本印出的 `wall_s` 为准。
- 训完开新对话,确认新专家被挂上;删掉之后不再挂。
- 用 Termux 路径时,对一下 `telemetry.log` 里的 RSS 是不是训练进程,而不是采样脚本自己。

这些桌面和模拟器都代替不了。

## CI

工作流 `.github/workflows/android-apk.yml`,名字 `Android APK`。在 `android/**` 或该工作流文件的 push / pull request 上跑。宿主已带 Android SDK,不再用 `android-actions/setup-android`(它会去装已经废弃的 `tools` 包)。步骤是装 SDK 35、NDK `27.2.12479018`、CMake 3.22.1、glslc,按 `android/trainer/build_android.sh` 编 OpenBLAS ARMv8 和 `libtrain-mft.so`,再按 `android/qvac/build_android.sh` 从 `tetherto/qvac-fabric-llm.cpp` 的 `b73e75af5` 加大小写补丁编 `libllama.so`(先试 Vulkan,着色器失败才退回 CPU),然后 `./gradlew testDebugUnitTest assembleDebug assembleDebugAndroidTest`。单元测试里有 Paparazzi 截图。产物名 **`lorabge-memory-arm64-debug`**,里面是签名调试 APK `app-debug.apk`。

签名不再用每次 CI 新生成的 `~/.android/debug.keystore`。Gradle 默认用仓库里的测试钥匙 `android/apk/keystore/debug-test-only.jks`(别名 `lorabge-test`,密码写在该目录的 README,标明只给测试)。四个仓库 Secret `ANDROID_KEYSTORE_B64`、`ANDROID_KEYSTORE_PASS`、`ANDROID_KEY_ALIAS`、`ANDROID_KEY_PASS` 都有值时改用那把钥匙。自动化账号不能写入 Secrets。换钥匙会再改一次签名。`versionCode` 由版本名算出来:主版本 * 1000000 + 次版本 * 1000 + 修订,所以 0.1.5 是 1005,0.1.6 是 1006,0.1.7 是 1007,0.1.8 是 1008,0.1.9 是 1009,0.1.10 是 1010,0.1.11 是 1011,0.1.12 是 1012,0.1.13 是 1013,0.1.14 是 1014,0.1.15 是 1015,0.1.16 是 1016,0.1.17 是 1017,高于已发布 0.1.4 的 1004,也高于已发布 0.1.2 的手写 versionCode 4 和旧标签 0.1.3 的 1003。

上一版下载 `29fe08c` zip、GEMM 仍是纯 C++ 的绿运行:[Android APK 39895706987](https://github.com/kingshuoxu/LoRA-bge-long-memory/actions/runs/39895706987)(push `61d2b0c`),同一提交的 pull request 运行 [39895710520](https://github.com/kingshuoxu/LoRA-bge-long-memory/actions/runs/39895710520)。本提交改为现场编 OpenBLAS 和 Vulkan `libllama`,运行 URL 写在 PR 描述里。产物名仍是 **`lorabge-memory-arm64-debug`**。解出来的 `libtrain-mft.so` 是 arm64 PIE,解释器 `/system/bin/linker64`,LOAD 对齐 `0x4000`,并链进 `cblas_sgemm`。

另有一个 `upgrade` 任务跑 `android/scripts/upgrade_preserve.sh`:在 x86_64 的 `aosp_atd` 模拟器上,用同一把钥匙安装 versionName 0.1.16(versionCode 1016,不含原生库),写入记忆、模型和 `shared_prefs`,再 `adb install -r` 0.1.17(1017),断言三样都还在。`inapp-update` 任务另装已发布的 arm64 `android-v0.1.4`,在带 ARM 翻译的模拟器里点「检查更新」,下载并走系统安装器升到已发布的 0.1.5,不使用 `adb install -r`。接着同一台模拟器跑 `connectedDebugAndroidTest`,用真输入法检查输入栏在键盘上方,圆点在跳,巩固一条事实时能看见步数,新对话能想起这条事实,开放问题「告诉我佐雷公司相关信息」答出 1979。星云像素看模拟器控制台录像。截图和 `nebula-gesture.mp4` 在该任务的 `upgrade-e2e` 产物里。arm64 镜像在 x86 宿主上仍然起不来,所以这个测试不装正式的 arm64 APK,也不拿已发布的 0.1.2 或旧标签上的 0.1.3(那两份签名不同,覆盖安装会失败)。发布工作流要等这个任务通过,并且仓库里有 `android/PUBLISH_OK`(截图和录像看过之后才放上),才上传 `android-v0.1.17`。0.1.17 把对话、巩固、记忆库和设置改成炭黑画布：助手正文不加气泡，用户消息是浅色圆角，输入栏是实心圆角条，来源知识是小标记，设置按卡片分组。星云仍是整页星空。教事实、助手口吻回忆、取消训练和加载模型的行为保持 0.1.16。这台云主机的嵌套 KVM 在 `KVM_CREATE_VCPU` 时会报 `kvm_spurious_fault`,本地起不来这个模拟器,所以覆盖安装和这条端到端的结果以 CI 的 `upgrade` 任务为准。

vivo X200 Pro 上星云曾停在一块不动的底色上：WebView 被盖住，点不了，Three.js 又只申请 WebGL2。0.1.3 让触摸进到页面，WebGL2 失败时改画 WebGL1，两种都没有就用 Compose 画粒子云、星和连线。控制台和 `gl.getParameter(RENDERER)` 进 logcat，也附在导出诊断里。改走兼容画面时只提示一次。「新」只标这次打开之后巩固出来的专家，导入的不算。模拟器任务会在 SwiftShader 上捏合、拖动、点开事实卡，录像在 `upgrade-e2e` 的 `nebula-gesture.mp4`。

vivo X200 Pro 上 0.1.2 的对话不再崩溃。0.1.3 接着修键盘挡住输入栏、生成时静止的省略号、巩固停在「损失 · 0 步」、开放问题不走记忆并让基座编造佐雷公司年份,以及陈述句只回一个名字。原生路由对「告诉我佐雷公司相关信息」常在事实闸门 `abstain_fact` 或没有业务线索时不开火,界面于是把问题交给基座。现在只要问句里的名字对上 `fact_memory.json` 里的实体,就用已存事实作答,不再生成;库里没有的那一项会写「其余不在记忆里」。这次路由的 `nativeFired` / `nativeReason` / `nativeSim` 记在 `files/setup/last-route.json`,导出诊断时附在末尾。「损失 · 0 步」是因为训练要攒满 8 个微批才打出第一行 `loss=`,状态文件以前不在这一步中间更新。现在 `:train` 每秒写心跳,第一步显示「这一步还在计算 · 已过 N 秒」。0.1.5 给这一步加了上限:每个微批开始打出 `[micro i/n] step k/m`,页面显示「第 k/m 步 · 微批 i/n」;超过 3 分钟没有新输出就失败,可以重试或取消。最后一步打出之后写适配器的那段安静时间不算卡住。

0.1.9 的对话有两处。换版本号不再把这台 Mali 上已经证明更快的 Vulkan 当成没测过，自检崩一次也不会永久改走 CPU。用户说「你好 我是徐金朔」时，回复是「好的，记住了，你是徐金朔。」，实体仍是「我」，星云显示「关于你」，下面写「已记下，待巩固」，不再把这句话交给基座，也不再自称这个名字。「某公司成立于某年」「总部在某地」只回「好的，记住了。」并放进待巩固。问句和「告诉我某公司相关信息」仍用已存事实或原来的回答。

这次运行的 URL 写在文末和 PR 描述里。

## 阻塞

1. **QVAC 的梯度是错的,已经换掉。** MobileFineTuner batch 8 第 4 个 epoch 是 **48/50**。APK 现在的调用是微批 1、累加 8。桌面上这套更新跑完 4 个 epoch,fp32 贪心和 f16 GGUF 都是 **49/50**(未中 b0-044)。不累加的 batch 1 第 1 个 epoch 是 **0/50**。跑满 12 个 epoch 会掉到 22/50。常识题不挂这个适配器:实体对不上,余弦最高 0.429。
2. **bge 的大写拉丁字母,桌面和手机现在走同一份补丁。** 桌面 12 条余弦最低 0.999998。APK 不再用 `29fe08c` 那个 zip,而是 QVAC `b73e75af5` 加 `wpm-cased.patch`。路由对照 11687/11687 仍是修之前的问句向量加 PyTorch 键,当时没有改判。没有改走 ONNX。
3. **训练源码对齐了,GEMM 目标不同。** 两边都是 MobileFineTuner `086b1a027fe708d5eaca89b1ec2bf1a876fb80de` 加 `mft-ffn-lora.patch`,都是 OpenBLAS、微批 1、累加 8。桌面打分是 x86 OpenBLAS;手机是 ARMv8 NEON。第 1 步 loss 已经对齐到 4.07324。对话和嵌入都是 QVAC `b73e75af5` 加大小写补丁;手机多一个 Vulkan 后端给 Adreno。`--val-split` 不再参与手机训练。
4. **界面按 PR #4 的桌面客户端对齐。** 底栏是对话、星云、巩固、记忆库。右上角齿轮进设置(后端、Wi-Fi、清单、语言、导出诊断、空间和版本),标题下不再放「基座 ok」这类调试状态。对话是气泡、输入栏里的发送图标、顶栏一个新对话,对话列表在抽屉里。星云把桌面的 WebGL 银河和粒子云放进 WebView,双指缩放,点专家展开事实星,点事实看属性、取值、来源对话和闸门分;回忆时高亮并写出相似度。专家名字用实体。0.1.2 起对话、嵌入、路由和 GPU 自检在 `:llm`,训练在 `:train`,Mali 要等这次独立自检对上并且更快才用 GPU。0.1.3 把设置改成不透的全屏,星云在手机比例下能看出粒子云和专家名字,巩固页用阶段星座和事实卡片,图形后端改走 CPU 时只提示一次,下载剩余时间不会显示 0 秒。模拟器在这台机器上起不来。对话、设置、下载、巩固的设备尺寸截图用 Paparazzi,星云用同一套页面在无头 Chrome 里截。
5. **官方模拟器拒绝在这台 x86_64 上启动 arm64 镜像。** 见上面的 FATAL。对话、Vulkan 和训练时长仍要真机。覆盖安装用 x86_64 的 `aosp_atd` 测数据还在不在,不代替 arm64 冒烟。

## 核对记录

- 逻辑路由四种情形 11687/11687,事实闸 11687/11687,实体抽取 5 个专家名单一致。
- `export_phone_bundle.py` 写出 5 个专家、事实向量 2250 行。这个目录在 `android/out/`,不入库。
- `qemu-aarch64-static` 跑静态 arm64 路由:实体问句挂上 `expert_0`,理由 `entity`。
- 本地 `./gradlew testDebugUnitTest assembleDebug assembleDebugAndroidTest` 通过。`MemoryStoreTest` 3 项 0 失败。签名调试 APK 只含 arm64-v8a,里面有 `libmemoryroute.so`、三条 QVAC 命令(改名为 `libllama-*.so`)和 ggml / vulkan 的 so。
- 模拟器没有装过带 arm64 原生库的正式 APK,原因见上一节。`upgrade_preserve.sh` 用去掉原生库的同签名包,在 x86_64 模拟器上验证 `adb install -r` 留下记忆、模型和设置。
- CI 运行 URL 在 PR 描述里。产物名 `lorabge-memory-arm64-debug`。

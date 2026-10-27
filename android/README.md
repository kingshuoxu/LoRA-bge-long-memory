# 长期记忆(小米 15)

安装包只含 arm64。包名 `com.lorabge.memory`。界面是深空底,底栏是对话、星云、巩固、记忆库。右上角齿轮进设置:推理后端、只在 Wi-Fi 下载、自定义清单、语言、导出诊断、已用空间和版本。星云用的是桌面同一套 WebGL(银河背景和粒子云),可以双指缩放、拖动,点开专家看事实星,再点事实看取值和来源对话。名字用实体,不显示内部编号。对话走实体优先、边界守卫、bge 相似度和事实闸。要改一条记忆,直接说出新事实,确认之后会重新训练。巩固页把确认过的事实按桌面同一套问法展开再训。训练时星空暂停,星云上会标「巩固中」。目录格式见 `docs/client_store.md`。数字见 `docs/android_milestone_1.md`。

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

对话和嵌入用的 `libllama.so` 从 QVAC 提交 `b73e75af5` 交叉编译,并打上 `android/qvac/wpm-cased.patch`,这样 bge 的大写词不会被折成小写。同一份库里有 Vulkan,也有按 `armv8.7-a+dotprod+i8mm` 编的 `libggml-cpu.so`。训练程序另外链一份 OpenBLAS ARMv8。

```bash
sh android/trainer/build_android.sh   # OpenBLAS ARMv8 + libtrain-mft.so
sh android/qvac/build_android.sh      # libllama.so、llama-cli、llama-embedding
cd android/apk && ./gradlew assembleDebug
```

签名调试包在 `android/apk/app/build/outputs/apk/debug/app-debug.apk`。GitHub Actions 工作流 `Android APK` 也会打出同名产物 `lorabge-memory-arm64-debug`。

## 装到手机

手机浏览器打开预发布里的 `app-debug.apk` 直接安装。第一次打开会自己下载对话基座、bge、训练用的 safetensors 和五个专家,装好就可以用,中间不用电脑。下载页能看到每个文件的进度、速度和当前镜像,可以暂停再继续,也可以只在 Wi-Fi 下下载。清单地址可以改成自己的 URL。

0.1.4 起发布包用同一把钥匙签名,钥匙在 `android/apk/keystore/debug-test-only.jks`,密码写在旁边的说明里,只给测试,不是上架密钥。打开应用,或在设置里点「检查更新」,会读 `android-v*` 发布列表和同目录的 `update.json`,不读 `releases/latest`。GitHub 连不上时改走 `gh-proxy.com`、`gh-proxy.org`、`ghfast.top`、`gh.llkk.cc` 和 `gh.nxnow.top`;HTML 落地页会跳过。`ghproxy.net` 和 `mirror.ghproxy.com` 不再使用。连不上时用中文说明,并给出发布页。`versionCode` 按 `主版本 * 1000000 + 次版本 * 1000 + 修订` 递增,0.1.7 是 1007,0.1.8 是 1008,0.1.9 是 1009。有新版本就给出说明,下载 APK 可以续传,对上 SHA256 之后用系统安装器覆盖安装。第一次要在系统里允许本应用「安装未知来源应用」。

已经装过 0.1.2、更早的包,或标签上那份旧的 0.1.3 的手机,签名对不上,要先卸一次。卸载会清掉应用内部目录和 `Android/data/com.lorabge.memory/` 里的模型、专家、对话和设置。模型下次打开会按 `android-v0.1.0` 的清单重新下载。卸完装上 0.1.4 之后,以后同一把钥匙的版本(包括 0.1.5)在应用里更新,这些数据都留着。清单里某个文件的 SHA256 变了才重新下那个文件。

0.1.5 的星云在半精度着色器或点精灵画出格子噪点时,改画同一页里的 canvas 粒子云。专家名字和事实卡还在。已经装了发布版 0.1.4 的手机不用卸载。

已经装了 0.1.4 或 0.1.5、但手机连不上 GitHub 的，这一次要用手机浏览器打开预发布里的 `app-debug.apk` 安装。0.1.4 里的检查更新还不会走新镜像。装上 0.1.6 之后，再检查更新才用新镜像和按标签读 `update.json`。同一把测试钥匙，不用卸载。

0.1.7 把星云压暗到更接近夜空，放大之后可以再缩回开场取景。关于自己的事实记在同一个「关于你」上，库里的实体仍是「我」。巩固页在训练 LoRA 时只画一条进度线。步数、微批和轮次用同一次状态：例如已经完成第 2 步、正在算第 3 步的第 6 个微批时，线和文字都是第 3/8 步、微批 6/8、第 2/4 轮。已经装了 0.1.6 的手机在应用里检查更新。还在 0.1.4 的手机仍要浏览器装一次。

0.1.8 再压暗缩到最小的开场星云。粒子按屏幕像素来画，拉远时不会变小，几朵云叠在一起中心会发白。这一版只在开场那一帧收掉最亮的核心和光刺，放大后与 0.1.7 一样亮。已经装了 0.1.7 的手机在应用里检查更新。还在 0.1.4 的手机仍要浏览器装一次。

0.1.9 让已经证明更快的 Vulkan 在换版本后继续用 GPU。自检崩一次不再永久改走 CPU。提示会写明阶段和信号。设置里把图形后端改成自动可以再试。描述知识时不再把原话复述一遍。「你好 我是徐金朔」回「好的，记住了，你是徐金朔。」，记在实体「我」上，星云显示「关于你」，回复下面是「已记下，待巩固」。「某公司成立于某年」只回「好的，记住了。」并放进待巩固。问句和开放回忆照常回答。已经装了 0.1.8 的手机在应用里检查更新。

0.1.10 把巩固页训练时底下的图改成一条损失曲线。原先上面一条正弦波不是损失，下面一条又把最高和最低拉满整张图。现在只画这一次训练的逐步损失，从 0 往上量，并标出「损失」和当前数值。第一步还没打出 loss 时不画波。已经装了 0.1.9 的手机在应用里检查更新。还在 0.1.4 的手机仍要浏览器装一次。

0.1.3 的星云在拿不到 WebGL2 时改用 WebGL1，再不行就用界面自己画粒子云，拖动、缩放和点事实都还在。右上角齿轮留在星云外面。导出诊断里带显卡字符串和页面报错。只有这次打开应用后新巩固的专家会标「新」。

0.1.3 还修了 vivo X200 Pro 上的这几件事。输入栏用 `adjustResize` 和根列上的 `imePadding`,键盘打开时底栏收起。生成时圆点会动,第一个词超过 3 秒会显示已等待多久。巩固页的阶段和桌面一致,训练在前台服务里每秒把步数、轮次、损失和剩余时间写进 `status.json`;第一步还在算时显示已过秒数。「我的猫猫叫咪咪」会记成实体「我」、属性「猫的名字」,并自己填上问句和回答,回复是「好的,记住了,你的猫叫咪咪。」还没训练的事实出现在记忆库的「待巩固」。问到已保存的实体时直接用库里的事实,不再交给基座编一个没有的年份;开放问题「告诉我佐雷公司相关信息」回答 1979。原生路由若因为事实闸门没过而没开火,原因会写进诊断里的 `last-route.json`。导入专家和路由自检挪到设置的「高级」。

仓库自动化写不了 GitHub Secrets。若要换成私钥,不要把 keystore 提交进 git,在自己的电脑上执行 `android/apk/keystore/README.md` 里的 `gh secret set`。四个 Secret 一旦设上,签名就换成那把钥匙,已经装了测试钥匙包的手机要再卸一次。在决定换钥匙之前不要设置它们。

镜像按这个顺序试,失败就换下一个:ModelScope、hf-mirror.com、huggingface.co,最后才是 GitHub Release。带 `bert-bge-cased` 的 bge 和五个专家只在这次发布的文件里。官方 f16 只有在字节和我们转换的那份完全一样时才会排在基座前面。

电脑上的 adb 仍然可以用,但不是必须的。手机开开发者选项和 USB 调试,数据线连上电脑,`adb devices` 能看到设备。然后:

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

打开「长期记忆」。设置 → 高级里点「导入已推送的专家」,再点「路由自检」,应显示「路由自检通过」。

## 在手机上试

1. 对话页新建对话,问「塔佐巴洛公司是哪一年成立的?」。挂上 `expert_0`、理由是实体,回答里有 1978。这五条在 Q8 上会错、在 f16 上桌面已经对过:b0-022、b0-026、b0-030、b0-031、b0-049,都是产品编号。
2. 再问一句和库无关的话,不应挂专家。
3. 巩固页顶部是和桌面一样的阶段星座。抽出的事实是一张卡片,上面有陈述句、实体、取值和确认过的问句。想马上训就勾「立即训练」。不勾的话要插着电,并且把屏幕关掉,训练才会开始。对话里如果听出一条新事实,回复下面会写「已记下,待巩固」,条目会填进巩固页,不在对话上展开训练。用户确认过的事实一定训练,哪怕闸门本来想跳过。
4. 通知栏能看到进度。`train/status.json` 是状态,`train/telemetry.tsv` 是耗时、RSS、热区、电量,`train/mft/` 是检查点。点「取消训练」会停掉进程。训练读的是 `models/Qwen2.5-0.5B-Instruct/`(safetensors、config、词表),不是 GGUF。
5. 训完,记忆库和星云里出现这个专家,名字来自事实里的实体。再开一个新对话,问刚才写入的那句,应挂到这个新专家。
6. 点删除,索引会重写,再问这句不应再挂它。

设置里可以选择自动、强制 GPU 或强制 CPU,当前后端写在那里,不放在标题下面。对话、bge 嵌入、路由和 GPU 自检都在 `:llm` 进程里,训练在 `:train`。界面进程不加载这些原生库,所以 Vulkan 或 JNI 崩了也不会回到桌面。自检本身也在 `:llm` 里,通过之前不会拿 GPU 回答。崩溃会写下信号、阶段、后端和回溯,导出诊断能看到。这块设备和驱动版本会被记成坏后端,同一条请求改走 CPU,界面弹出一次提示,不会一直留在输入栏上。设置页是不透的全屏,底下的标题不会透出来。星云在手机上把每个专家画成能看清的粒子云,事实是云里的星,名字和事实卡能读,开场就把所有专家放进画面。自动时,模型下完会用一句很短的解码和一条嵌入跟 CPU 对一下。Vulkan 起不来、进程崩了,或者结果对不上,就记住 CPU,下次不再试。小米 15 的 Adreno 830 只看结果是否一致,路径和以前一样。vivo X200 Pro 的 Mali-G925(厂商号 0x13B5)会关掉 cooperative matrix 和 bf16,保留 fp16 存储和运算,tile 按 16 宽子组来排,不再把子组抬到 32。自动模式在 Mali 上先保持 CPU,只有独立进程里的自检对得上、并且短解码比 CPU 快,才升到 GPU。训练始终在 CPU 上,OpenBLAS 只占 cpufreq 里的大核和超大核:小米 15 两档 Oryon 是 8 线程,天玑 9400 的 1+3+4 是 4 线程。这份 OpenBLAS 用 `NO_AFFINITY=1` 编译。交叉编译时宿主是 Linux,不关绑核的话第一次 `cblas_sgemm` 会在手机上停住,巩固页就一直停在 `[Dataset]` 那一行。每个微批开始会写出步数;超过 3 分钟没有新输出就失败,可以重试或取消。

llama.cpp 的 OpenCL 后端是按 Adreno 的 `cl_qcom` 写的,没有 Mali 路径,这份包不加 OpenCL。MediaTek NeuroPilot 也没有能直接跑这份 llama.cpp 的后端,没有接上。

设置里的「导出诊断」写成一份文本,并打开系统分享。里面有厂商、型号、SoC、GPU、后端、线程数、各核最高频率,以及 GPU 和 CPU 的预填充、解码 tok/s,还有 Vulkan 设备名、驱动版本、子组宽度、特性和原生崩溃记录(信号、阶段、后端、回溯)。基准模式写的 `benchmark.json` 里的 `device` 字段相同。

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

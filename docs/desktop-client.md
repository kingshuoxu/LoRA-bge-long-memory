# 桌面客户端

本地多轮对话。每一句都会走仓库里的 bge 路由：相似度够了、实体守卫也通过，就挂上对应的 LoRA 专家，否则用基座回答。对话保存在本机。

勾选一则或多则旧对话，点「巩固所选」。程序抽出可以长期记住的事实（陈述句和问答），你改完再写入。训练在后台进行，能看进度，也能取消后接着训。训完会登记路由键、实体和 `fact_memory.json`，之后的新对话会用到这条记忆。

界面可以在中文和英文之间切换，选择记在本机设置里，第一次打开跟系统语言。这份说明仍是中文。英文对话会按英文句式抽取事实，巩固和纠正走同一套向量，不另加关键词表。

## 技术栈

- **记忆库 `memory_core/`**：路由、抽取、写门、训练、专家目录。不依赖界面。研究脚本的函数签名没有改，`scripts/router.py` 的 `embed`、`router_key`、`extract_entities_from_key_texts`、`extract_query_entity`、`verify_entity_guard` 仍是原来的实现。
- **本地服务 `backend/server.py`**：只监听 `127.0.0.1`，提供页面和接口。
- **桌面壳 Electron**：窗口打开上面这个本机页面。用 Electron 而不是只发源码，是因为安装包要在普通 Ubuntu 上直接跑：AppImage 自带浏览器运行时，不依赖系统 WebKit，也不需要显卡。macOS 的 dmg、Windows 的安装程序也是同一套 electron-builder 打出来的。
- **内置 Python**：安装包里有一份独立的 CPython 3.12 和 PyTorch。Linux / Windows 打的是 CPU 轮子，没有 NVIDIA 驱动也能训练。macOS 用官方轮子，机器支持时走 MPS。代码在 CUDA、MPS、CPU 之间自动选；CPU 上训练和推理都是 float32。

训练超参跟实验结论对齐：LoRA `r=32`、`alpha=64`，只训 FFN（`gate_proj` / `up_proj` / `down_proj`），学习率 `5e-4`，最多 12 轮，loss 不再下降或出现晚期发散就停，并留下 loss 最低的那一轮。损失只算在助手回答上。

## 安装包

GitHub Actions 工作流 `.github/workflows/desktop-packages.yml` 会打出这些产物：

| 系统 | 产物名 | 文件 |
|---|---|---|
| Linux x64 | `lora-memory-linux-appimage-deb` | `.AppImage` 和 `.deb` |
| Windows x64 | `lora-memory-windows-nsis` | NSIS 安装程序 `.exe` |
| macOS arm64 | `lora-memory-macos-arm64-dmg` | `.dmg` 和给自动更新用的 `.zip` |
| macOS Intel x64 | `lora-memory-macos-x64-dmg` | `.dmg` 和给自动更新用的 `.zip` |

安装包不含模型，也不含仓库里那五个研究专家（那些权重在 Git LFS 里）。第一次打开会下载模型。

## 第一次运行会下载的模型

开发模式和命令行没有设置 `LORA_MEMORY_MODELS` 时：仓库里已经有 `models/` 就用那一份，否则用 `~/.cache/lora-bge-memory/models/`。`LORA_MEMORY_MODELS` 可以改位置。国内网络下载模型可以设 `HF_ENDPOINT=https://hf-mirror.com`。

安装包里的对话、专家和模型不在程序目录里，更新只替换程序。打包后的应用把这些都放在 Electron 的 userData：

- Linux：`~/.config/lora-bge-memory/`（尊重 `$XDG_CONFIG_HOME`），模型在其中的 `models/`
- macOS：`~/Library/Application Support/lora-bge-memory/`
- Windows：`%APPDATA%\lora-bge-memory\`

第一次打开安装包时，如果新目录还缺文件，会把旧位置补过来：Linux 上是 `~/.local/share/lora-bge-memory/` 和 `~/.cache/lora-bge-memory/models/`。macOS 和 Windows 的旧目录本来就和 userData 相同。新目录里已经有的文件不会被盖掉。权重尺寸够了就不会重新下载。

命令行和端到端脚本不设 `LORA_MEMORY_MIGRATE`，仍用上面的开发默认目录。`LORA_MEMORY_HOME` 可以改对话目录。

| 目录 | Hugging Face 仓库 | 实测体积 |
|---|---|---|
| `Qwen2.5-0.5B-Instruct` | `Qwen/Qwen2.5-0.5B-Instruct` | 999,605,157 字节（约 954 MB）。其中 `model.safetensors` 为 988,097,824 字节 |
| `bge-small-zh-v1.5` | `BAAI/bge-small-zh-v1.5` | 96,408,718 字节（约 92 MB）。其中 `model.safetensors` 为 95,827,648 字节 |

两个合计约 1.05 GB（1,096,013,875 字节）。下载中断再打开会接着下。命令行的对话和专家仍在：

- Linux：`~/.local/share/lora-bge-memory/`
- macOS：`~/Library/Application Support/lora-bge-memory/`
- Windows：`%APPDATA%\lora-bge-memory\`

`LORA_MEMORY_HOME` 可以改这个目录。安装包用的是上面的 userData，第一次打开会把 Linux 的这份旧目录补过去。

## 在没有 GPU 的 Ubuntu 上安装并做端到端检查

下面这条路径不需要显示器，也不需要 root 以外的显卡驱动。验收脚本会：新建一段写了四条虚构事实的对话，巩固，在 CPU 上训练专家，再开一则新对话把这四条问出来，并确认常识题和几道 CMMLU 风格的选择题不会挂上这个新专家。

### 用 AppImage（不需要 root）

1. 从工作流产物 `lora-memory-linux-appimage-deb` 里取出 `LoRA-bge-memory-0.2.0-linux-x86_64.AppImage`（文件名里的架构是 `x86_64`，不是 `x64`）。
2. 在 x86_64 的 Ubuntu 22.04 或 24.04 上：

```bash
chmod +x LoRA-bge-memory-*-linux-x86_64.AppImage
./LoRA-bge-memory-*-linux-x86_64.AppImage --appimage-extract
bash squashfs-root/resources/e2e-check.sh
```

`--appimage-extract` 只解包，不挂 FUSE，也不打开窗口。无界面验收不需要 `libfuse2`。

要打开图形界面时，双击 AppImage 需要系统里有 FUSE 2。Ubuntu 22.04 上的包名是 `libfuse2`。Ubuntu 24.04 上的包名是 `libfuse2t64`（`libfuse2` 只是指向它的过渡包，有时源里没有）。可以先装上：

```bash
sudo apt-get install -y libfuse2t64 || sudo apt-get install -y libfuse2
```

没有 `libfuse2` / `libfuse2t64`、又不想装时，用下面这条启动，它会把包解到临时目录再运行，不挂 FUSE：

```bash
chmod +x LoRA-bge-memory-*-linux-x86_64.AppImage
APPIMAGE_EXTRACT_AND_RUN=1 ./LoRA-bge-memory-*-linux-x86_64.AppImage
```

脚本结束时看这几行：

```text
E2E_SCORE 4/4
E2E_PARAPHRASE 10/10
E2E_ABSTAIN 14/15
E2E_GENERAL_ACTIVATED 0/5
E2E_CMMLU_ACTIVATED 0/5
E2E_CORRECTION 1/1
```

`E2E_PARAPHRASE` 是训练问句里没有逐字出现过的改写，要至少 90%。`E2E_ABSTAIN` 是同一个人没写过的属性（狗、汽车颜色、生日等），要至少 90% 回基座。上面那次 CPU 生成验收是 10/10 和 14/15。事实闸后来把属性阈值调到 0.685，同一批 15 条里「沈星河养的狗叫什么名字？」不再挂上猫，弃权是 15/15；「最喜欢的咖啡」也不会挂上茶。口语里的「单车 / 骑的那辆车 / 家住在哪个镇 / 老家」仍低于这条线，因为再放低就会把咖啡和狗放进来。`E2E_CORRECTION` 是在这些检查之后把猫的名字从云朵改成暮雪并重新训练：新对话回答「暮雪」，不再出现「云朵」，住址仍是青岚镇。第一次训练 best loss 0.0586，第 8 轮按 patience 停下，四条主问题回忆 4/4。纠正那一轮 best loss 0.0474，第 9 轮按 target 停下，回忆仍是 4/4。设备是 CPU，float32，学习率 5e-4。

`E2E_SCORE` 不是 `4/4`、改写或弃权低于 90%，或 `E2E_CORRECTION` 不是 `1/1` 时，进程退出码为 1。第一次运行会先下载上面两个模型（合计约 1.05 GB）。模型已经在本机时，这四条事实在 4 核 CPU 上大约一分钟，纠正会再训一轮。早停留在 loss 最低的检查点。核数更少会更久；几十条事实会久得多。数据写在 `~/.local/share/lora-bge-memory-e2e/`（每次运行会清空这个目录，不会动你平时的对话）。完整记录在该目录的 `e2e-report.json`。

### 用 deb

```bash
sudo apt-get update
sudo apt-get install -y ./LoRA-bge-memory-*-linux-amd64.deb
lora-bge-memory-e2e
```

`apt` 会装上 Electron 依赖的图形库。deb 的依赖写成 `libgtk-3-0 | libgtk-3-0t64` 这一类二选一，Ubuntu 22.04 和 24.04 都能解析；24.04 上已实际安装通过。安装脚本会放两个命令：`/usr/bin/lora-bge-memory` 指向 `/opt/LoRA-bge-memory/lora-bge-memory`，`lora-bge-memory-e2e` 跑无界面验收。验收命令本身仍然不打开窗口。

同一条安装脚本把 `/opt/LoRA-bge-memory/chrome-sandbox` 设成 `4755`（root setuid）。没有这个权限时，普通用户开窗口可能报 sandbox 错误。可以再执行一次：

```bash
sudo chown root:root /opt/LoRA-bge-memory/chrome-sandbox
sudo chmod 4755 /opt/LoRA-bge-memory/chrome-sandbox
```

或者临时用 `lora-bge-memory --no-sandbox`。

装好后的图形界面：

```bash
lora-bge-memory
```

### 在图形界面里手工走一遍

模型下完之后：

1. 点「新对话」，逐条发送：
   - `沈星河的猫的名字是云朵。`
   - `沈星河的住址是青岚镇。`
   - `沈星河的自行车颜色是朱红色。`
   - `沈星河最喜欢的茶是桂花乌龙。`
2. 勾选这则对话，点「巩固所选」。巩固页会按真实进度列出：选中的对话、逐条出现的事实、写门留下或跳过的原因、编出来的训练样本、每一轮的 loss 和预计剩余时间、用主问题做的回忆检查，以及登记专家时写入的路由键。核对事实后点「开始巩固」。可以取消，取消之后点「继续训练」。
3. 训练结束提示写入之后，打开「星云」。每位专家是一团星云，事实是星，来源对话是节点。可以缩放、拖拽、悬停，点一颗星能看到事实、来源摘录、所属专家和是否还在生效。点「新对话」，分别问：
   - `沈星河的猫的名字是什么？` → 云朵
   - `请问沈星河的住址是什么？` → 青岚镇
   - `沈星河的自行车颜色是什么？` → 朱红色
   - `沈星河最喜欢的茶是什么？` → 桂花乌龙
4. 回答旁边应出现「记忆 · 沈星河」，而不是「基座」。旁边的星云会亮起整份专家，以及事实闸对上的那颗星；悬停能看到路由键分数、问句分、属性分和阈值。这是整份 LoRA 挂载，不是每颗星各有一份权重。点回答下的「回忆自」可以再亮一次。问一个没写过的问题，星云不亮，并显示「未调用记忆」。
5. 再问「水的化学式是什么？」或一道与沈星河无关的选择题，应保持「基座」，星云不亮。
6. 打开「记忆库」可以看到事实和来源对话。删除之后，再问沈星河，应回到基座，并且不会挂到别的专家上。
7. 若某条事实记错了，可以在对话里直接说出新的取值（例如「沈星河的猫的名字不是云朵，正确的是暮雪。」），或在星云里点开那颗星、填上新取值。程序会用向量对上那条事实、给出改写后的陈述，确认后把旧事实标成已取代，并重新训练同一位专家。星云里旧星变暗、新星点亮。之后再问猫的名字，应回答新取值，住址等其他事实仍在。提问不会被当成纠正。

界面里的星云和整窗星空都用打包进去的 three.js 与本地着色器绘制，运行时不访问 CDN。标题用随包的 Cormorant Garamond 和 Noto Serif SC，正文用 EB Garamond 和 Noto Serif SC。训练进行时星空会变暗并降帧，免得和训练抢资源。系统开了「减少动态效果」时动画停在一帧。右上角可以切换中文和英文。验收在原有分数之外还会打印 `E2E_CORRECTION`：纠正训练结束后，新对话里猫的名字应为暮雪且不再出现云朵，住址仍是青岚镇。这一步会再训一轮。

## 从源码运行

```bash
python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv/bin/pip install -r requirements-desktop.txt
# macOS 不要加 cpu 索引，直接 pip install torch，这样才有 MPS

# 模型会在第一次对话时下载；也可以预先放到 models/
cd desktop
npm install
npm start
```

仓库里如果已经有 `models/`，程序会用那一份，不再下载。

只跑验收、不打开窗口：

```bash
PYTHONPATH=. .venv/bin/python -m memory_core.e2e_check --models models
```

## 自己打安装包

三个系统都是同一条命令，在对应的机器或 CI  runner 上执行。先装 Node.js 22。

```bash
python3 packaging/build_runtime.py
cd desktop
npm ci
# 没有证书时不要让 electron-builder 去找签名身份
export CSC_IDENTITY_AUTO_DISCOVERY=false   # Windows 是 set CSC_IDENTITY_AUTO_DISCOVERY=false
npx electron-builder --publish never
```

- Linux 还需要 `fakeroot`、`dpkg`。产物在 `desktop/dist/`：AppImage 和 deb。建议在 Ubuntu 22.04 上打，glibc 更老，22.04 和 24.04 都能跑。
- Windows 产物是 NSIS 的 `.exe`。
- macOS arm64 用 `macos-15` 一类的 Apple Silicon runner，Intel 用 `macos-15-intel`。产物是 `.dmg` 和 `.zip`。zip 给已签名应用的自动更新用，dmg 给手动替换。

## 应用内更新

安装包用 electron-updater。发布标签是 `desktop-v` 加 `desktop/package.json` 里的版本，例如 `desktop-v0.2.0`，并且是 GitHub Release 的预发布。标签推上去之后，工作流把四个系统的产物收成一份 Release，里面有 `latest.yml`、`latest-mac.yml`、`latest-linux.yml`、安装包和 blockmap。两份 macOS 的 `latest-mac.yml` 会把 `files` 合并，避免 arm64 和 x64 互相盖掉。

客户端启动后，以及设置里的「检查更新」，都会去找最新的 `desktop-v*` 预发布。更新说明显示在设置和顶部提示里。Windows 的 NSIS 和 Linux 的 AppImage 在后台下载，然后点「重启并更新」。文件名里没有版本号的 AppImage 会在原地覆盖，快捷方式不用改。

deb 不能原地替换。它只提示有新版本，并给出下载链接，同时把 deb 下到用户数据目录的 `updates/`。

macOS 的静默更新走 Squirrel.Mac，只接受带 Developer ID 的签名，并且当前系统还要公证，否则替换后的应用会被 Gatekeeper 拦住。临时签名（`codesign -s -`，签名是 adhoc，没有 `Authority=Developer ID Application`）没有稳定的团队身份，公证也不能盖在临时签名上，所以自动更新不会生效。没有 Developer ID 时，客户端改成下载对应架构的 dmg，并提示把新应用拖进去替换。用户数据在应用包外面，替换不会清掉。

GitHub 下载慢时，可以在设置里填一个镜像地址。镜像目录要和 Release 一样，放 `latest.yml`、`latest-mac.yml`、`latest-linux.yml`、blockmap、安装包，以及 `desktop-release.json`。客户端先试 GitHub，请求超时或失败再试镜像。

各系统要准备的密钥：

- Linux：不用密钥。AppImage 自动更新，deb 只给下载链接。
- Windows：不用密钥也能自动更新。SmartScreen 可能提示未知发布者。要 Authenticode 签名时，把 p12 做 base64 放进 Actions secret `CSC_LINK`，密码放进 `CSC_KEY_PASSWORD`。工作流只有在 `CSC_LINK` 有值时才打开 `signAndEditExecutable`。
- macOS：静默更新需要 Apple Developer Program 的 Developer ID Application 证书，以及公证。证书同样用 `CSC_LINK`（p12 的 base64）和 `CSC_KEY_PASSWORD`。公证二选一：`APPLE_ID`、`APPLE_APP_SPECIFIC_PASSWORD`、`APPLE_TEAM_ID`，或者 `APPLE_API_KEY`、`APPLE_API_KEY_ID`、`APPLE_API_ISSUER`。这些 secret 要加在仓库的 Actions secrets 里。拉取请求默认不签名。只有 Developer ID、没有公证，在现在的 macOS 上也不够。没这些 secret 时，安装包不签名，用户按提示手动替换 dmg。

已经装过、但那一版还没有更新代码的客户端，要手动装一次这个版本，之后才能在应用里更新。

`packaging/build_runtime.py` 会下载 [python-build-standalone](https://github.com/astral-sh/python-build-standalone) 的 CPython 3.12.15（release `20261021`）。Linux 和 Windows 安装 CPU 版 PyTorch；macOS 安装 PyPI 上的官方包（含 MPS）。

## 记忆怎么存

用户训练出来的专家在数据目录的 `experts/expert_1000/` 这一类文件夹里：

- `adapter_model.safetensors`：LoRA 权重
- `router_key.pt`：bge 路由键，一条事实文本一个向量
- `key_texts.json`：和路由键对齐的文本
- `fact_memory.json`：实体、陈述、问答、来源对话
- `fact_spans.pt`：每条事实单独的问句向量和属性短语向量
- 上一级的 `router.jsonl`、`fact_gate.json`：登记表和阈值（旧专家的路由键读取 τ=0.6，新专家的事实语义闸 τ=0.622，写入去重 0.94）

读取时：问句里如果出现某条新记忆登记过的实体，就先看那个专家（实体优先）。`verify_entity_guard` 要精确相等；问句若把「那辆」「养的」这类词吞进名字里，只要这个更长的写法仍以登记的实体开头，就继续往下看，不在守卫这里拒掉。比较前把实体换成「某」、取值换成「某值」，拉丁字母再忽略大小写。问句不能更像另一条事实，并且要么几乎重合于某条已存问句（≥ 0.91），要么问句 ≥ 0.622 且属性短语也过线（中文 0.685，英文 0.80），才挂上这个专家。问句如果点了在册的人，只和这个人的事实比。对不上就回基座，不会因为句式里出现了这个人就把没写过的属性（比如只记了猫，却问狗）交给它。巩固时本地模型会为每条事实改写几句问法，只放进事实闸；改写若更像另一条事实，或和原问句不够像，就丢掉。仓库里原来的五个专家没有 `fact_memory.json`，桌面路由对它们仍是「最大相似度 + 实体守卫」，和 `scripts/eval_memory.py` 一致。没点名新专家时，新专家的路由键不参与 top-1。

删除只去掉被点名的那个专家。问句里的实体如果不在剩下的专家名册里，守卫会把请求打回基座，不会因为问法相似就挂到别的专家上。

抽取不使用 CEO、成立年份、总部、旗舰产品这张固定表。能从原句里直接看到「谁的什么是什么」就抽；企业四类句式仍会调用原来的 `scripts/extract_qa_pipeline.py`。实体和取值必须是原文里的子串。写门和 `scripts/auto_write.py` 一样用 0.94 去重。和已有记忆太像、又没被勾上的事实不训练。基座碰巧已经说对的事实会标成「基座已经知道」，但只要用户确认就仍然登记并训练。

## 设备

| | 训练 | 推理 |
|---|---|---|
| CPU | float32，lr 5e-4 | float32 |
| CUDA（Windows / Linux，且当前 torch 带 CUDA） | float32 | float16 |
| MPS（macOS 官方 torch） | float32 | float32 |

DirectML 不用于训练。研究记录里它的 loss 和 CPU 对不上。

Linux / Windows 安装包里的 PyTorch 是 CPU 轮子，`torch.cuda.is_available()` 为假。有 NVIDIA GPU、又想用 CUDA 时，在安装包自带的解释器里换成 CUDA 轮子，例如：

```bash
/opt/LoRA-bge-memory/resources/runtime/bin/python3 -m pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cu124 --force-reinstall
```

这一步体积大，而且这次提交没有在 GPU 上跑过。

## 已知限制

- 本仓库的验证机是 Linux CPU。macOS 和 Windows 的安装包由 CI 编译并上传，没有在对应系统上打开过。
- 没有填上面的签名 secret 时，安装包不签名。macOS 第一次打开需要在「隐私与安全性」里放行。Windows SmartScreen 可能提示未知发布者。临时签名不能让 macOS 自动更新。
- 基座是 Qwen2.5-0.5B。巩固前请看一眼抽出的事实，小模型会漏，也会说多余的话；原文对不上的会被丢掉。
- CPU 训练比 GPU 慢。一次只巩固少量事实是可以接受的；几十条以上会久得多。
- 默认安装包不含 CUDA。MPS 只在 macOS 的官方 torch 里，这次没有在 Mac 上实测。
- 研究用的五个专家要另放。把 `LORA_MEMORY_REPO_EXPERTS` 指到克隆下来的 `experts/`（需先 `git lfs pull`），聊天时会和用户专家一起路由。安装包本身不带这 250 MB 权重。
- 晚于收敛继续训会把记忆擦掉。客户端最多 12 轮，并保留 loss 最低的检查点；取消发生在当前 step 结束时，已完成的轮次可以继续。

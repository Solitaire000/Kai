# 小K (Kai) —— 私人秘书 Agent

部署在移动硬盘上、可在多台电脑间切换使用的个人助理agent。
在线模型优先，断网自动降级到本地离线模型；记忆系统与模型完全解耦，换模型/断网都不丢记忆。

---

## 一、目录结构

```
kai_agent/
├── config/
│   ├── config.yaml            # 主配置：模型路由、记忆参数
│   └── secrets.example.yaml   # API key模板，复制成 secrets.yaml 后填真实key
├── core/
│   ├── model_router.py        # 模型路由：直接尝试在线服务商，失败给出具体原因，自动降级本地
│   ├── memory.py               # 三层记忆系统（线程安全，网页版可用）
│   ├── embeddings.py           # 语义检索用的向量嵌入
│   ├── network.py              # 联网检测（仅供/status参考，不再拦截在线请求）
│   ├── secrets_loader.py       # 从硬盘上的secrets.yaml加载API key
│   └── agent.py                # 主控agent
├── agents/
│   ├── base_agent.py
│   └── specialized_agents.py   # 生活/日程/科研/工作 四个子agent
├── web/
│   ├── templates/index.html    # 网页版聊天界面
│   └── static/{style.css, app.js}
├── web_app.py                  # 网页版启动入口：python web_app.py
├── skills/                     # 技能系统：让小K能在权限范围内操作电脑，见「八、Skills」
│   ├── README.md                # 怎么加一个新技能（拓展接口说明）
│   ├── get_datetime/            # 内置技能：查日期时间
│   ├── get_system_info/         # 内置技能：查系统信息
│   ├── list_dir/                # 内置技能：列目录（只读）
│   ├── read_file/               # 内置技能：读文件（只读）
│   ├── write_file/               # 内置技能：写文件（危险，需确认）
│   ├── open_path/                # 内置技能：打开文件/网址（危险，需确认）
│   └── run_command/              # 内置技能：执行shell命令（默认整个关闭）
├── data/
│   ├── workspace/               ← 技能系统的沙盒目录，文件类技能默认只能碰这里面
│   ├── models/                  ← 本地离线GGUF模型放这里
│   ├── adapters/                ← LoRA训练产出的adapter版本目录
│   ├── eval/                    ← 回归检查用的评测集
│   └── probes/                  ← 主动探测用的题库
├── memory/                      ← 与「记忆」相关的一切都在这里，见 docs/MEMORY_MODEL.md
│   ├── memory.db                (首次运行自动生成，运行时三层记忆)
│   ├── vector_store/            (首次运行自动生成，语义检索向量库)
│   ├── training_samples.db      ← 日常对话自动积累的原始蒸馏问答流水账
│   ├── identity/                ← 身份/边界锚定语料（主人格）
│   │   ├── identity_anchors.jsonl
│   │   └── subagents/           ← 每个子agent专属身份锚定
│   └── knowledge/               ← 提炼语料 + 旧大脑主动探测快照（换base model用）
├── train/                       ← LoRA训练脚本，见 train/README_TRAINING.md
├── migrate/                     ← 换base model/换provider的工具链，见 migrate/README.md
├── hardware/                    ← 硬件设备接入层，见 hardware/README.md 和 docs/HARDWARE_ARCHITECTURE.md
│   ├── base_device.py            # 所有硬件驱动必须实现的公共接口
│   ├── serial_transport.py        # USB转串口设备共用的连接层（端口发现+重连）
│   └── devices/
│       └── mr60bha2_breath/       # Seeed MR60BHA2毫米波呼吸心率传感器
│           ├── device.yaml
│           ├── driver.py
│           ├── firmware/          # 烧录到ESP32上的固件
│           └── README.md          # 接线/烧录/排障指南
├── docs/
│   ├── MEMORY_MODEL.md          # 记忆模型总览：运行时记忆 vs 训练侧记忆资产
│   ├── SUBAGENT_COEVOLUTION.md  # 子agent"总览+咨询+共同进化"架构设计
│   ├── TOOLS_VS_SKILLS.md       # Tool/Skill/子agent咨询/硬件工具怎么区分
│   └── HARDWARE_ARCHITECTURE.md # 硬件接入的完整架构：分层设计、非阻塞原则、智能性怎么落地
├── scripts/
│   ├── setup_env.bat / .sh          # 首次在新电脑上运行一次（venv方案）
│   ├── setup_embed_windows.bat      # 没装Python/没安装权限的电脑用（自动配置便携Python）
│   ├── start_kai.bat / .sh          # 日常启动（命令行版）
│   └── start_web.bat / .sh          # 日常启动（网页版，带模型选择+语音）
├── main.py
├── voice/
│   ├── CosyVoice          # 首次在新电脑上运行一次（venv方案）
├── venv
├── voice/
│   ├── CosyVoice/
│       ├── venv/			# 虚拟环境
│       ├── CosyVoice/		# git 项目
│       ├── pretrained_models		# 预训练模型
│       ├── tts_server.py
│   	└── setup_env.bat / .sh
└── requirements.txt
```

---

## 二、在线模型为什么加载不了（问题排查）

用 `python main.py` 或网页版跑起来后输入 `/status`（网页版看左侧"系统状态"面板），
逐条对照检查，原因通常是下面几个之一，**新版已经把每一条失败原因都会明确显示出来，不再是笼统的"离线降级"**：

### 1. 有两个服务商的 key 从来没换成真的
`config/secrets.yaml` 里 `SILICONFLOW_API_KEY` 和 `ZHIPU_API_KEY` 之前一直是占位符
`"xxxxxxxxxxxxxxxx"`。这两个必须去对应平台申请真实key填进去才能用，不填就会被跳过
（这是设计上的正常行为，不是bug，只是之前没有任何提示告诉你"跳过了"）。

### 2.（这是最主要的架构性bug，已修复）联网探测用错了站点，把"能用"误判成"不能用"
旧版 `model_router.py` 的逻辑是：**先探测 `baidu.com`/`aliyun.com` 能不能连上，连不上就直接
不去尝试任何在线模型，直接走本地模型。** 而你的 `scripts/setup_env.bat` 里专门写了"清除代理
环境变量，否则pip装包容易失败"这样的注释 —— 说明你机器上经常需要开代理/VPN才能访问
OpenRouter、Anthropic这类境外服务。**代理环境下，"能不能连上baidu.com"和"能不能连上
openrouter.ai"经常是互相矛盾的**（全局代理模式下baidu可能变慢/不通；分流代理下baidu本身没走代理
但也可能因为其他原因超时）。一旦这个探测判断错误，系统会**完全跳过所有在线服务商**，
即使你的OpenRouter key本身是有效的、网络也是通的，也永远用不上——这完全符合你说的"无法成功"
的现象。

**新版修复**：不再用一个不相关的网站来"一票否决"是否尝试在线模型。现在会直接尝试每一个
已启用且配了key的服务商，用**这次请求本身**的异常类型来判断到底是网络问题还是服务问题
（key错误/模型名不存在/欠费限流/网络超时），原因会完整展示在回复下方和 `/status` 里。

### 3. 请求没有超时设置，网络不通时会卡很久才报错
旧版调用 `OpenAI` 客户端时没传 `timeout`，网络异常时可能要等SDK默认的超时时间（很长）才会
失败，体验上就像"卡住了/无法成功"。新版给每个请求加了20秒的显式超时。

### 4. Anthropic (Claude) 服务商默认是关闭的
`config.yaml` 里 `anthropic` 这一项 `enabled: false` 是故意的默认设置（怕你没配key就产生调用
成本），这不是bug。要用的话把它改成 `true`，并在 `secrets.yaml` 里填 `ANTHROPIC_API_KEY`。

### 5. 生成内容陷入复读循环
在你原来的 `memory/memory.db` 里发现一条历史记录，模型回复陷入了"查询天气查询天气查询天气…"
的复读循环——这是免费/低价模型常见的退化现象，不是模型没加载，而是加载成功了但生成质量差。
新版给在线和本地模型调用都加上了 `frequency_penalty` / `repeat_penalty`，能明显缓解这个问题。

### 6.（已修复）网页版偶尔弹出一个完全空白的对话框
根因在 `core/model_router.py::_call_one_provider()`：某些在线服务商/免费模型偶尔会返回一次
"成功"的响应，但 `message.content` 是 `None` 或空字符串——比如那次请求模型什么都没生成。
旧版直接把这个空文本当成正常结果原样返回，导致三个连锁问题：① 不会去尝试下一个服务商或
降级到本地模型（因为路由层认为这次调用"成功"了）；② 网页版收到 `text: null`，前端
`body.textContent = null` 渲染出一个看不出发生了什么的空气泡；③ 因为标记成"非降级"，这条
空回复差点还会被当成训练样本记进 `memory/training_samples.db`。

**修复**：`_call_one_provider()` 和本地模型的 `_chat_local()` 现在都会检测到空文本，前者当成
失败处理（继续尝试下一个服务商 / 最终降级到本地模型），后者（已经是最后一道保险，没有下一个
可以退）会返回一句明确的兜底提示而不是空字符串。`core/agent.py` 和网页版前端
`web/static/app.js` 也各加了一道防御性检查，双重保险，确保空文本不会一路传到你眼前变成一个
莫名其妙的空气泡。

### 排查步骤建议
1. 打开网页版或CLI，看 `/status`：哪些服务商显示"占位符key"就去补真实key，哪些显示
   "未启用"就去 `config.yaml` 里打开。
2. 如果显示"已配置"但对话还是失败，看回复下面的"调用失败详情"，会直接告诉你是
   401(key错误)/404(模型名错误)/429(限流欠费)/网络超时中的哪一种。
3. `qwen/qwen3.6-plus:free` 这个模型名如果提示 404/模型不存在，去 openrouter.ai/models
   确认一下当前这个免费模型的准确id有没有变化（免费模型池会不定期调整）。

---

## 三、首次部署步骤

### 1. 配置API key
```
cp config/secrets.example.yaml config/secrets.yaml
# 然后编辑 secrets.yaml 填入你的真实key
```
key放在硬盘上的文件里而不是系统环境变量，就是为了插到哪台电脑都不用重新配置。

### 2. （可选但推荐）下载本地离线兜底模型
去 Hugging Face 或国内镜像 hf-mirror.com 下载 GGUF 格式模型，放到 `data/models/`：

- 电脑性能一般：**Qwen2.5-1.5B-Instruct-GGUF**（Q4_K_M量化，约1GB）
- 电脑性能尚可：**Qwen2.5-3B-Instruct-GGUF**（Q4_K_M量化，约2GB，config.yaml默认配的是这个）

国内下载建议用 hf-mirror：
```
# Linux/Mac
export HF_ENDPOINT=https://hf-mirror.com
huggingface-cli download Qwen/Qwen2.5-3B-Instruct-GGUF qwen2.5-3b-instruct-q4_k_m.gguf --local-dir data/models
```
Windows下没有huggingface-cli也没关系，直接在浏览器打开 hf-mirror.com 搜模型名手动下载 .gguf 文件放进 `data/models/` 即可。

**这一步不做也完全能用**——只是断网时小K会提示本地模型未配置，不影响联网时的正常使用。

### 3. 初始化环境
- Windows：双击 `scripts/setup_env.bat`
- Mac/Linux：`bash scripts/setup_env.sh`

会在硬盘上创建一个便携虚拟环境（`venv/`），依赖也装在这个目录里，不污染宿主电脑。

### 4. 日常启动
- 命令行版：
  - Windows：双击 `scripts/start_kai.bat`
  - Mac/Linux：`bash scripts/start_kai.sh`
- **网页版**（带模型选择下拉框 + 语音聊天，推荐）：
  - Windows：双击 `scripts/start_web.bat`
  - Mac/Linux/Termux：`bash scripts/start_web.sh`
  - 启动后浏览器打开 `http://127.0.0.1:8420`

---

## 四、网页版界面：模型选择 + 文字/语音聊天

`python web_app.py` 启动后，浏览器打开 `http://127.0.0.1:8420`：

- **左上角 ⋮ / 侧栏**：下拉框里能看到所有 `config.yaml` 里配置的在线模型 + 本地离线模型，
  每个选项前面 ✓/× 表示"现在选它能不能用"，× 的话下面会写清楚原因（没配key/占位符key/
  模型文件没下载）。选"自动"就是原来的自动路由逻辑；选具体某个模型就是强制只用它，
  方便你测试某个服务商到底通不通。
- **文字聊天**：正常打字，回车发送（Shift+回车换行）。每条回复下面的小字标签
  （比如 `general/openrouter_qwen` 或 `general/local_gguf · 离线降级`）说明是哪个子agent、
  哪个模型来源回答的，和CLI版的 `[agent/source]` 标签是一个意思。
- **语音聊天**：麦克风按钮用的是浏览器自带的 Web Speech API 做语音识别，"自动朗读回复"
  开关用的是浏览器自带的语音合成——**没有装任何额外的Python语音库**，因为这类库
  （pyaudio、pyttsx3等）在手机/嵌入式Python环境下经常装不上或者行为不一致，用浏览器
  自带能力反而更稳。Chrome / Edge（电脑和手机）支持最好；Safari对语音识别支持有限，
  文字聊天不受影响。
- **记忆**：侧栏"让小K记住一件事"对应CLI里的 `/remember`；效果和CLI共用同一个
  `memory/memory.db`，两边切换用互不影响。

这个网页服务本身没有账号系统、没有公网暴露，默认只监听本机+局域网，适合个人单机使用；
不要把 `8420` 端口直接暴露到公网（比如做端口转发），它没有任何身份验证。

---

## 五、手机部署

网页版天生就是"能装在手机上"的方案，有两种路子，按你的手机情况选一种：

### 方案A：Android + Termux，小K真正跑在手机上
1. 应用商店/F-Droid 装 **Termux**
2. Termux 里执行：
   ```bash
   pkg update && pkg install python
   pip install flask openai pyyaml requests numpy
   # llama-cpp-python 在手机上编译很慢/容易失败，一般不建议在手机上装，
   # 用在线模型即可；真要本地兜底可以试 pip install llama-cpp-python，失败也不影响在线功能
   ```
3. 用 Termux 的文件管理把项目文件夹传到手机上（或者 `git clone` / `termux-setup-storage` 后从存储里复制），进入项目目录：
   ```bash
   cp config/secrets.example.yaml config/secrets.yaml   # 填好key
   python web_app.py
   ```
4. 手机自带浏览器打开 `http://127.0.0.1:8420` 即可，语音功能用 Chrome for Android 支持最好。
5. 想让Termux常驻后台不被系统杀掉，装个 `termux-wake-lock`，或者用 Termux:Boot 插件开机自启。

**优点**：完全独立，不需要电脑在旁边。**缺点**：手机上跑Python环境相对小众，出问题不如
电脑好排查；iOS 没有对等的 Termux，这条路基本只适用于 Android。

### 方案B：电脑常驻跑服务，手机纯当浏览器客户端（推荐，尤其iOS用户）
1. 小K照常部署在电脑/迷你主机/树莓派上，跑 `python web_app.py`（它默认监听
   `0.0.0.0`，已经允许局域网访问）。
2. 电脑上查一下局域网IP（Windows: `ipconfig`；Mac/Linux: `ifconfig`/`ip addr`），
   比如 `192.168.1.10`。
3. 手机连同一个WiFi，浏览器打开 `http://192.168.1.10:8420` 即可，iOS/Android 都能用。
4. 想出门在外也能用（不在同一WiFi下），可以装 **Tailscale**（电脑和手机都装，加入同一个
   tailnet），用 Tailscale 分配的地址代替局域网IP访问，相当于免公网IP、免内网穿透配置的
   私有隧道，安全性也比直接暴露端口好得多。

**优点**：省电、不占手机资源、更容易维护，iOS也能用。**缺点**：电脑得开着（迷你主机/树莓派
7x24跑着正合适）。

---

## 六、便携Python方案怎么选：venv vs python_embed

结论先说：**默认用 venv（`setup_env.bat/.sh`），只有在目标电脑完全没装Python、又没有
安装权限时才用 python_embed，两者可以按"主力用venv + 应急带一份embed"的方式共存，不冲突**。

| | **venv（本地虚拟环境）** | **python_embed（官方免安装便携版）** |
|---|---|---|
| 前提条件 | 目标电脑已装Python | 完全不需要目标电脑装任何东西 |
| 装依赖 | 正常pip，网络好的话几分钟搞定 | 一样能pip装纯Python包；`llama-cpp-python`官方也发布了预编译wheel，一般也能装 |
| 维护成本 | 低，出问题好排查，生态成熟 | 偏高：没有pip自带（需要手动get-pip.py引导）、`._pth`要手动改一行、遇到需要编译的包容易踩坑 |
| 体积 | 略大（含完整stdlib） | 更小 |
| 适用场景 | **默认首选**，覆盖你绝大多数使用场景 | 只在"公司电脑没有安装权限""临时借同事电脑"这类场景下应急 |

**具体建议**：
1. 日常使用（自己的3台电脑）：都用 `setup_env.bat/.sh` 走 venv 方案，最省心。
2. 如果确实经常需要在"没有Python/没有安装权限"的电脑上用（比如经常出差借用陌生电脑），
   在**自己电脑上**先跑一次新增的 `scripts/setup_embed_windows.bat`，它会自动下载配置好
   `python_embed/`（包含pip、修好`._pth`、装好依赖），配置好之后**整个 `python_embed` 文件夹
   跟着项目一起放在移动硬盘里**，插到任何Windows电脑上都能用 `python_embed\python.exe main.py`
   或双击 `start_kai.bat`/`start_web.bat`（这两个脚本已经改成会自动优先检测`python_embed`，
   没有的话再找venv）直接跑，不需要再联网下载。
3. 不建议"每次插到新电脑都现场下载配置embed"——python.org不在很多内网/国内网络的
   快速通道里，现场下载体验会很差。提前在自己电脑上配置好、整份带走，才是这个方案真正
   的价值所在。
4. Mac/Linux 场景没有对等的embeddable方案（也用不上，因为Mac/Linux机器几乎总是自带
   Python3），直接用venv即可。
5. 手机（Termux）场景不适用venv也不适用python_embed，见上一节「手机部署」，直接用
   Termux自带的pip装到系统python里即可，手机上没有"多套隔离环境"的强需求。

---

## 七、日常使用

命令行版：
```
你: 帮我整理一下今天要做的事
小K [schedule/siliconflow]: ...

你: /status                    # 查看当前联网状态、各模型配置情况
你: /models                    # 列出所有可选模型（含就绪状态）
你: /use openrouter_qwen       # 强制切到指定模型，/use auto 恢复自动路由
你: /remember 专业=RF探针视觉检测   # 显式让小K记住一件事
你: /exit
```

网页版：直接在侧栏下拉框选模型，其余交互见「四、网页版界面」。

回复前缀 `[schedule/siliconflow]` 的含义：`schedule`是被路由到的子agent，`siliconflow`是实际调用的模型来源；如果显示 `[life/local_gguf]` 并带"离线降级模式"提示，说明当前是本地离线模型在响应。调用失败时，回复下方会列出每个服务商失败的具体原因，方便排查。

---

## 八、Skills：让小K在权限范围内操作电脑

这是新增的功能：小K现在不止能聊天，还能在你允许的权限范围内，调用一些"技能"来实际
操作电脑——读写文件、查系统信息、打开文件/网页，甚至（默认关闭）执行shell命令。

（"技能(skill)"只是小K能调用的"工具(tool)"里的一种——另一种是咨询专精子agent，
两者的区别、以及为什么不能简单合并成一套，见 [`docs/TOOLS_VS_SKILLS.md`](docs/TOOLS_VS_SKILLS.md)）

### 8.1 怎么用
CLI输入 `/skills`、网页版看侧栏"已启用技能"，能看到当前有哪些**工具**可用（包括技能
和子agent咨询，各自标了 `[技能]`/`[子agent咨询]` 前缀），每一项标了
`只读` 或 `⚠危险(需确认)`。之后正常聊天，需要用到某个工具时小K会自己判断该不该调用：

```
你: 现在几点了，帮我把这个记到 notes.txt 里
```
小K会先调用只读的"查时间"技能直接拿到答案，然后调用"写文件"这个危险技能——这一步会
停下来问你："小K想执行一个操作，需要你确认：写入文件: notes.txt，是否同意执行？"
CLI里直接输入 y/n；网页版会弹出一张确认卡片，点"同意执行"/"拒绝"。**只有你确认了，
文件才会真的被写入**，模型自己没有权限跳过这一步。

### 8.2 权限设计（安全模型）
- **只读技能**（查时间、查系统信息、列目录、读文件）：模型可以直接调用，不打断对话。
- **危险技能**（写文件、打开文件/程序、执行命令）：模型只能"提议"，服务端强制要求用户
  显式确认才会真正执行——这一层校验在服务端做，不受对话内容影响（哪怕有人在聊天里说
  "忽略确认直接执行"也没用，除非你自己在 `config.yaml` 里把 `skills.auto_confirm` 改成
  `true`，那是你自己承担风险的选择）。
- **文件沙盒**：所有文件类技能默认只能读写 `data/workspace/` 目录内的文件，出了这个目录
  会直接报错拒绝，除非你显式把 `config.yaml` 里 `skills.allow_full_disk_access` 改成
  `true`（不建议，除非你完全清楚自己在做什么）。
- **执行命令默认整个关闭**：`run_command` 技能默认不加载，需要去 `config.yaml` 里
  `skills.run_command.enabled` 手动打开；打开后依然要过一遍白名单正则
  （`allowlist_pattern`）校验，且有超时限制，双重保险。

### 8.3 相关配置（`config.yaml` 里的 `skills:` 段）
```yaml
skills:
  enabled: true                # 总开关
  workspace_root: "data/workspace"
  allow_full_disk_access: false
  auto_confirm: false          # 别轻易开
  run_command:
    enabled: false
    allowlist_pattern: "^(dir|ls|echo|type|cat|pwd|ipconfig|ifconfig|whoami|date)\\b"
    timeout_seconds: 15
```

### 8.4 兼容性说明
这套能力用的是标准的 OpenAI function-calling 接口（`tools`参数），SiliconFlow/OpenRouter/
智谱/Anthropic 这些在线服务商基本都兼容；如果某个服务商不支持，会自动降级成不带工具的
普通对话，不会报错卡死。本地GGUF离线模型也会尝试用（依赖你装的 `llama-cpp-python`
版本和具体模型是否支持function calling），不支持的话同样自动降级为纯文字对话——离线时
小K照样能聊天，只是暂时用不了"操作电脑"这部分能力。

### 8.5 怎么加自己的技能
见 `skills/README.md`——新建一个文件夹放 `skill.yaml`+`handler.py` 就行，不用改任何
`core/`代码，重启小K自动生效。比如你可以照着现有的写一个"查一下GSG探针检测程序跑到
哪一步了"这样的专属技能。

---

## 九、扩展指南

### 加一个新的在线模型
编辑 `config/config.yaml`，在 `online_providers` 下加一项即可，不用改任何代码：
```yaml
- name: my_new_provider
  base_url: "https://xxx/v1"
  api_key_env: "MY_NEW_KEY"
  model: "xxx-model-name"
  tier: "cheap"
  enabled: true
```
加好之后，CLI的 `/models`、网页版的模型下拉框会自动出现这个新选项，不用改 `model_router.py`
或前端代码。

### 加一个新的子agent
在 `agents/specialized_agents.py` 里仿照现有的写一个新类（继承 `SubAgent`，写好 `keywords` 和 `system_prompt`），加进 `ALL_AGENTS` 列表即可。

### 记忆系统怎么继续演化
现在是SQLite+本地向量库的最小可用版本。以后数据量大了，可以把 `MemoryStore` 内部实现换成 Chroma/其他向量数据库，只要对外方法名（`add_episodic`/`search_semantic`等）不变，`agent.py` 完全不用改——这就是当初做分层解耦的意义。

### 加一个新的硬件设备
`hardware/devices/<设备名>/` 下写 `device.yaml`（设备清单）+ `driver.py`（继承
`hardware.base_device.HardwareDevice`），重启小K会自动发现并加载，不用改
`core/hardware_manager.py`。完整步骤和接口约定见 [`hardware/README.md`](hardware/README.md)；
为什么这么设计（分层、非阻塞、智能性怎么体现）见
[`docs/HARDWARE_ARCHITECTURE.md`](docs/HARDWARE_ARCHITECTURE.md)。

---

## 十、硬件扩展：让小K接入真实的物理设备

小K现在能接入通过USB连接在PC上的硬件设备，第一个例子是
**Seeed MR60BHA2 60GHz毫米波呼吸心率传感器**（非接触式测呼吸率/心率/在场
状态，主控是套件自带的 XIAO ESP32C6）。

- 硬件本身怎么接线、固件怎么烧录：[`hardware/devices/mr60bha2_breath/README.md`](hardware/devices/mr60bha2_breath/README.md)
- 整体架构（为什么不阻塞对话、agent的判断和硬件数据怎么分离、以后怎么加新硬件）：[`docs/HARDWARE_ARCHITECTURE.md`](docs/HARDWARE_ARCHITECTURE.md)

几个关键设计点：

- **不影响正常聊天**：硬件的连接、断线重连全部在后台线程里做，网页版的
  请求线程只读内存里缓存的最新状态，从不直接等待硬件。默认关闭
  （`config.yaml` 里 `hardware.enabled: false`），不接硬件的人完全无感。
- **模型自己判断，不是硬编码规则**：`read_vital_signs` 是一个普通的
  只读工具，什么时候查全凭模型自己判断上下文要不要查；传感器状态变化
  （比如有人进入检测范围）会被记成一条"硬件观测"事实，下次对话时模型能
  看到，但要不要提、怎么提，同样是模型自己的判断，代码里没有任何
  "心率超过多少就提醒"这类阈值规则。
- **技能(skill)、子agent咨询、硬件工具是三种不同的东西**：这三者的区别、
  为什么用户/模型看到的东西容易混淆、怎么解决，见
  [`docs/TOOLS_VS_SKILLS.md`](docs/TOOLS_VS_SKILLS.md)。

---

## 十一、后续路线图（对应之前讨论的阶段划分）

- ✅ 阶段0：便携环境骨架 + 模型路由（含离线降级）
- ✅ 阶段1：三层记忆系统
- ✅ 阶段2：基础对话agent
- ✅ 阶段3：关键词路由的多子agent（当前是规则路由，后续可升级成模型判断路由）
- ✅ 阶段3.5：网页版UI（模型手动选择 + 浏览器语音）、模型路由错误可视化、手机部署方案
- ✅ 阶段3.6：**独立核心模型迭代闭环**（数据采集+离线LoRA微调+回归评测），详见 [train/README_TRAINING.md](train/README_TRAINING.md)；换base model时的记忆继承方案见 [train/README_INHERITANCE.md](train/README_INHERITANCE.md) 和 [docs/MEMORY_MODEL.md](docs/MEMORY_MODEL.md)
- ✅ 阶段3.7：**硬件设备接入**（MR60BHA2毫米波传感器为第一个例子），详见 [docs/HARDWARE_ARCHITECTURE.md](docs/HARDWARE_ARCHITECTURE.md)
- ⬜ 阶段4：场景专精化——比如把科研agent直接接到你现有的GSG探针代码库上，加文件读写工具、代码执行工具
- ⬜ 阶段5：画像记忆自动提炼（现在需要 `/remember` 手动记，后续可以让主控每隔几轮对话自动总结更新画像）
- ⬜ 阶段6：网页版加个简单的身份验证（哪怕只是一个共享密码），如果以后想通过公网/Tailscale之外的方式访问
- ⬜ 阶段7：真正的"本地核心大脑主控"架构（见 [train/README_TRAINING.md](train/README_TRAINING.md) 里的远期方向）——让本地模型决定何时外包给在线大模型，而不是反过来
- ⬜ 阶段8：更多硬件设备接入（跌倒检测、环境传感器等），复用 `hardware/` 的接入规范

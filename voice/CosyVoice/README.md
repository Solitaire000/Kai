# 小Kai 语音服务(CosyVoice 本地部署)

本文件夹包含"小Kai"语音功能的全部部署文件,使用 CosyVoice 官方内置音色(不做声音克隆),
和 chat 后端一起启动、一起关闭。

## 目录结构(部署完成后)

```
your_project/                  <- 你的智能体项目根目录
├── app.py                     <- 你的 chat 后端(Flask)
├── web/
├── venv/voice_venv
└── voice/CosyVoice                     <- 本文件夹,放在项目根目录下
    ├── requirements.txt
    ├── list_voices.py
    ├── tts_server.py
    ├── start_all.py           <- 一键启动 chat + 语音服务
    ├── stop_all.py            <- 关闭后台运行的服务
    ├── CosyVoice/              <- 第三方仓库(需要 git clone 下来)
    └── pretrained_models/      <- 模型文件(下载后自动生成)
    └── bat/      <- bat
```

## 部署步骤

### 1. 把这个 voice 文件夹放到你的项目根目录下

保证目录结构和上面一致,尤其是 `config.yaml` 里 `chat.cwd: ".."` 要能正确指到
你项目根目录(也就是 app.py 所在目录)。

### 2. 安装 CosyVoice 本体(在 voice 文件夹内进行)

```bash
cd voice

# 建议用独立的 conda 环境,避免和 chat 后端的依赖冲突
conda create -n cosyvoice python=3.10 -y
conda activate cosyvoice

git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git
cd CosyVoice
conda install -y -c conda-forge pynini==2.1.5
pip install -r requirements.txt
cd ..

# 安装 voice 文件夹自身需要的依赖
pip install -r requirements.txt
```

> 注意: `tts_server.py` 里 `sys.path.append("third_party/Matcha-TTS")` 这行,
> 假设的是从 `voice/CosyVoice/` 目录内运行。如果你把 `CosyVoice` 仓库克隆在了
> `voice/` 目录下,请把 `tts_server.py`、`list_voices.py` 这两个文件挪到
> `voice/CosyVoice/` 目录里(和 `third_party` 同级),或者相应修改
> `sys.path.append` 的相对路径。这是本文档里唯一需要按你实际克隆位置微调的地方。

### 3. 下载模型

```bash
python download_model.py
```

### 4. 试听内置音色,选一个当"小Kai"

```bash
python list_voices.py
```

生成的样本在 `voice_samples/` 文件夹,听完后把喜欢的音色名填入
`config.yaml` 里的 `tts.voice_name`(默认已经填了 `中文男`,可以直接跳过这步)。

### 5. 确认 chat 启动命令

打开 `config.yaml`,确认 `chat.command` 是你实际启动 chat 后端的命令。
按你目前的代码(`app.run(host="0.0.0.0", port=port, ...)` + Flask),
大概率是:

```yaml
chat:
  command: ["python", "app.py"]
```

如果入口文件不叫 `app.py`,改成实际文件名即可。

### 6. 让 chat 后端调用语音服务

在你 `app.py` 里,LLM 生成回复文本后,加一步调用本地语音服务,
再把音频地址/数据一起返回给前端:

```python
import requests

def get_kai_voice(text: str) -> bytes:
    resp = requests.post(
        "http://localhost:8001/api/tts",
        data={"text": text},
    )
    return resp.content  # wav 音频二进制
```

前端(网页)收到回复后播放:

```javascript
async function speakKai(text) {
  const res = await fetch('/api/tts_proxy', { method: 'POST', body: JSON.stringify({ text }) });
  const blob = await res.blob();
  new Audio(URL.createObjectURL(blob)).play();
}
```

(具体是让前端直接打 8001 端口,还是走 chat 后端转发一层 `/api/tts_proxy`,
看你现有前后端的跨域/架构习惯,两种都可以。)

## 日常使用:一键启动 / 关闭

### 启动(前台运行,推荐日常开发用)

```bash
cd voice
python start_all.py
```

会依次启动:小Kai语音服务(先加载模型)→ chat 后端。
**按 `Ctrl+C` 会同时关闭两个服务。**
如果其中一个服务意外崩溃退出,另一个也会被自动一起关闭。

### 后台运行(比如部署为长期服务)

```bash
cd voice
nohup python start_all.py > run.log 2>&1 &
```

关闭时:

```bash
python stop_all.py
```

## 常见问题

- **语音服务启动很慢**:模型加载(尤其首次)本身需要十几秒到几十秒,`start_all.py`
  里已经预留了 15 秒等待时间再启动 chat,如果你的显卡较慢,可以把 `start_all.py`
  里 `time.sleep(15)` 调大一点。
- **端口冲突**:TTS 服务端口在 `config.yaml` 的 `tts.port` 改,chat 后端调用的地址
  (`get_kai_voice` 函数里的 URL)要跟着一起改。
- **纯 CPU 环境**:能跑,但每次合成可能要几秒到十几秒,建议先用 `list_voices.py`
  测一下单次合成耗时,评估是否满足对话场景的实时性要求。

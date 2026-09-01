"""
小Kai 本地 TTS 服务 (基于 CosyVoice 内置音色)
启动: python tts_server.py
默认监听 config.yaml 中 tts.port 指定的端口(默认 8001)

调用方式(供 chat 后端使用):
    POST http://localhost:8001/api/tts
    form-data: text=你好呀

    返回: audio/wav 二进制音频
"""
import sys
import io
import os
import soundfile as sf

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# 获取当前脚本所在的绝对目录（即E:\Kai\kai_agent\voice）
SCRIPT_ROOT = os.path.dirname(os.path.abspath(__file__))
# 拼接得到CosyVoice项目根目录的绝对路径
cosyvoice_path = os.path.join(SCRIPT_ROOT, "CosyVoice")
# 拼接得到第三方依赖库的绝对路径
matcha_tts_path = os.path.join(cosyvoice_path, "third_party", "Matcha-TTS")
# 将两个路径加入Python模块搜索路径
sys.path.append(cosyvoice_path)
sys.path.append(matcha_tts_path)
print("已配置的CosyVoice路径：", cosyvoice_path)
print("已配置的Matcha-TTS路径：", matcha_tts_path)
print("已配置的config路径：",BASE_DIR+"/config/config.yaml")

import yaml
import torchaudio
import uvicorn
from fastapi import FastAPI, Form
from fastapi.responses import StreamingResponse
from cosyvoice.cli.cosyvoice import CosyVoice

import torch
if torch.cuda.is_available():
    torch.cuda.set_device(0)
    print("Using GPU:", torch.cuda.get_device_name(0))
else:
    print("CUDA unavailable, using CPU")

os.environ['MODELSCOPE_ENABLE_HTTP'] = '0'  # 禁用HTTP请求


with open(BASE_DIR+"/config/config.yaml", "r", encoding="utf-8") as f:
    CFG = yaml.safe_load(f)["tts"]

app = FastAPI(title="Kai Voice Service")

print("[小Kai语音服务] 正在加载 CosyVoice 模型,请稍候...")
cosyvoice = CosyVoice(CFG["model_dir"])
VOICE_NAME = CFG["voice_name"]
print(f"[小Kai语音服务] 模型加载完成,当前音色: {VOICE_NAME}")


@app.get("/health")
async def health():
    return {"status": "ok", "voice": VOICE_NAME}


@app.post("/api/tts")
async def tts(text: str = Form(...)):
    buffer = io.BytesIO()
    for result in cosyvoice.inference_sft(text, VOICE_NAME):
        # torchaudio.save(buffer, result["tts_speech"], 22050, format="wav")
        audio = result["tts_speech"].cpu().numpy()
        # sf.write(f"test.wav", result["tts_speech"].numpy().squeeze(), 22050)
        sf.write(
            buffer,
            audio.T,
            22050,
            format="WAV"
        )
        break  # 简单场景取第一段;文本很长时可考虑分句拼接
    buffer.seek(0)
    return StreamingResponse(buffer, media_type="audio/wav")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=CFG["port"])

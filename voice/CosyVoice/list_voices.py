"""
查看模型自带的所有音色,并逐个生成试听音频
运行: python list_voices.py
生成的 wav 文件会保存在 voice_samples_{model_name}/ 文件夹下,挑一个满意的
填回 config.yaml 里的 voice_name 字段
"""
import sys
import os
import soundfile as sf
from load_pretrained_model import *
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
from cosyvoice.cli.cosyvoice import CosyVoice
import torchaudio
import yaml

print(BASE_DIR+"/config/config.yaml")
with open(BASE_DIR+"/config/config.yaml", "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)["tts"]
    

print("加载模型中...")
# cosyvoice = CosyVoice(cfg["model_dir"])
# voices = cosyvoice.list_available_spks()
# print(f"共发现 {len(voices)} 个内置音色: {voices}")
# sample_text = "你好,我是小Kai,很高兴认识你。"
# for v in voices:
    # print(f"正在生成音色 [{v}] 的试听样本...")
    # for result in cosyvoice.inference_sft(sample_text, v):
        # safe_name = v.replace("/", "_")
        # sf.write(f"voice_samples_{model_name}/{safe_name}.wav", result["tts_speech"].numpy().squeeze(), 22050)
        # break
        
cosyvoice = load_cosyvoice_model(cfg["model_dir"],cfg["version"])
voices = get_available_speakers(cosyvoice,cfg["version"])
print(f"共发现 {len(voices)} 个内置音色: {voices}")

model_name = os.path.basename(cfg["model_dir"].rstrip('/\\'))
os.makedirs(f"voice_samples_{model_name}", exist_ok=True)
sample_text = "你好,我是小Kai,很高兴认识你呀！有什么可以帮到你的嘛？"
for v in voices:
    print(f"正在生成音色 [{v}] 的试听样本...")
    for result in inference_sft(cosyvoice,sample_text,v,cfg["version"]):
        safe_name = v.replace("/", "_")
        sf.write(f"voice_samples_{model_name}/{safe_name}.wav", result["tts_speech"].numpy().squeeze(), 22050)
        break

print("\n全部生成完毕,请前往 voice_samples_{model_name}/ 文件夹逐个试听。")
print("选定后,把音色名称填入 config.yaml 的 tts.voice_name 字段。")

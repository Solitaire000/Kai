"""
下载 CosyVoice 官方预训练模型(自带音色版本,不需要声音克隆)
只需运行一次: python download_model.py
"""
from modelscope import snapshot_download

if __name__ == "__main__":
    print("开始下载 CosyVoice-300M-SFT 模型(约几百MB,首次下载稍等)...")
    snapshot_download(
        "iic/CosyVoice-300M-SFT",
        local_dir="pretrained_models/CosyVoice-300M-SFT",
    )
    print("模型下载完成,已保存到 pretrained_models/CosyVoice-300M-SFT")

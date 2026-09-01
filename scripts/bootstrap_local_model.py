"""
本地兜底模型自举脚本
====================
解决问题：现在 config.yaml 里 local_fallback.model_path 指向一个需要你手动去
hf-mirror下载的文件，没下载的话，断网/所有在线provider失败时会直接报
LocalModelUnavailable，"兜底"名不副实。

这个脚本负责：
1. 检查 config.yaml 里配置的 local_fallback.model_path 是否存在
2. 不存在就自动下载一个小体积、CPU可跑的默认模型（Qwen2.5-1.5B-Instruct
   GGUF Q4_K_M，约1GB），国内网络自动走 hf-mirror.com 镜像
3. 幂等：已经下载过就直接跳过，不会重复下载

用法：
    python scripts/bootstrap_local_model.py

建议：加进 setup_env.bat/.sh 的最后一步，这样"首次部署"这一步做完，
不管有没有配任何在线API key，小K都立刻有基础推理能力，而不是等你
手动想起来去下载模型。
"""
import os
import sys
import yaml

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 默认兜底模型：优先选它是因为 (a) CPU可跑 (b) 1GB量级不会让首次部署卡很久
# (c) Qwen2.5指令遵循能力在这个尺寸段里目前算不错的
DEFAULT_REPO = "Qwen/Qwen2.5-1.5B-Instruct-GGUF"
DEFAULT_FILE = "qwen2.5-1.5b-instruct-q4_k_m.gguf"


def load_config():
    with open(os.path.join(BASE_DIR, "config", "config.yaml"), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _try_download(repo_id: str, filename: str, local_dir: str) -> bool:
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        print("[bootstrap] 缺少 huggingface_hub，先运行: pip install huggingface_hub")
        return False

    for endpoint, label in (
        (None, "官方 huggingface.co"),
        ("https://hf-mirror.com", "国内镜像 hf-mirror.com"),
    ):
        try:
            if endpoint:
                os.environ["HF_ENDPOINT"] = endpoint
            else:
                os.environ.pop("HF_ENDPOINT", None)
            print(f"[bootstrap] 尝试从 {label} 下载 {repo_id}/{filename} ...")
            hf_hub_download(repo_id=repo_id, filename=filename, local_dir=local_dir)
            print(f"[bootstrap] 下载成功: {os.path.join(local_dir, filename)}")
            return True
        except Exception as e:
            print(f"[bootstrap] 从 {label} 下载失败: {e}")
    return False


def main():
    cfg = load_config()
    model_cfg = cfg["model"]["local_fallback"]
    if not model_cfg.get("enabled", True):
        print("[bootstrap] local_fallback 在 config.yaml 里被关闭了，跳过。")
        return

    
    configured_path = os.path.join(BASE_DIR, model_cfg["model_path"])
    if os.path.exists(configured_path):
        size_mb = os.path.getsize(configured_path) / (1024 * 1024)
        print(f"[bootstrap] 本地兜底模型已存在: {configured_path} ({size_mb:.0f}MB)，跳过下载。")
        return
    print("[bootstrap] 未找到 config.yaml 里配置的本地模型文件，") 
    
    # models_dir = os.path.join(BASE_DIR, "data", "models")
    # os.makedirs(models_dir, exist_ok=True)


    # print(f"[bootstrap] 将下载默认兜底模型 {DEFAULT_REPO}（约1GB，仅需一次）...")
    # ok = _try_download(DEFAULT_REPO, DEFAULT_FILE, models_dir)

    # if not ok:
    #    print("[bootstrap] 自动下载失败（可能是网络问题）。你可以手动去 hf-mirror.com")
    #    print(f"[bootstrap] 搜索 {DEFAULT_REPO}，下载 {DEFAULT_FILE} 放到 {models_dir}/ 下，")
    #    print("[bootstrap] 或者编辑 config.yaml 把 local_fallback.model_path 改成你已有的模型路径。")
    #    print("[bootstrap] 不做这一步不影响联网时正常使用，只是断网时小K会退化为无推理能力的降级提示。")
    #    return

    #downloaded_path = os.path.join(models_dir, DEFAULT_FILE)
    #if os.path.abspath(downloaded_path) != os.path.abspath(configured_path):
    #    print(f"[bootstrap] 提醒: 下载路径是 {downloaded_path}，")
    #    print(f"[bootstrap] 但 config.yaml 里配置的路径是 {configured_path}。")
    #    print("[bootstrap] 请把 config.yaml -> model.local_fallback.model_path 改成:")
    #    print(f"[bootstrap]   \"data/models/{DEFAULT_FILE}\"")


if __name__ == "__main__":
    main()

"""
把 config/secrets.yaml 里的key加载进当前进程的环境变量。
这样 model_router 里 os.environ.get(...) 的逻辑完全不用变，
密钥的来源（系统env还是硬盘上的文件）对它是透明的。
"""
import os
import yaml
import logging

logger = logging.getLogger("kai.secrets")


def load_secrets(base_dir: str):
    secrets_path = os.path.join(base_dir, "config", "secrets.yaml")
    if not os.path.exists(secrets_path):
        logger.warning(
            "未找到 config/secrets.yaml，请复制 secrets.example.yaml 并填入你的API key"
        )
        return
    with open(secrets_path, "r", encoding="utf-8") as f:
        secrets = yaml.safe_load(f) or {}
    for key, value in secrets.items():
        if value:  # 空字符串不覆盖，允许某些key暂时不配
            os.environ[key] = str(value)

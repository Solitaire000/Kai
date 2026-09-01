#!/bin/bash
# 启动网页版界面（文字+语音聊天，可手动选模型）
# Mac/Linux/Termux(Android) 通用
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$PROJECT_DIR/venv"

cd "$PROJECT_DIR"

if [ -f "$VENV_DIR/bin/activate" ]; then
    source "$VENV_DIR/bin/activate"
    python web_app.py
elif command -v python3 &> /dev/null; then
    echo "[小K] 未检测到venv，直接用系统python3运行（适合Termux等场景）"
    python3 web_app.py
else
    echo "[错误] 未找到可用的Python，请先运行 setup_env.sh 或安装python3"
    exit 1
fi

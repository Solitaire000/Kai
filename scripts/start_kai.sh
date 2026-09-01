#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$PROJECT_DIR/venv"

cd "$PROJECT_DIR"

if [ -f "$VENV_DIR/bin/activate" ]; then
    source "$VENV_DIR/bin/activate"
    python main.py
elif command -v python3 &> /dev/null; then
    echo "[小K] 未检测到venv，直接用系统python3运行（适合Termux等场景）"
    python3 main.py
else
    echo "[小K] 未找到venv，也没有可用的python3。"
    echo "先运行 ./setup_env.sh，或者手动安装python3。"
    exit 1
fi

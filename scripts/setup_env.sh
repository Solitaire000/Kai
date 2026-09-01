#!/bin/bash
# First-time setup on a new Mac/Linux machine.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$PROJECT_DIR/venv"

echo "[Kai Setup] Project dir: $PROJECT_DIR"

if ! command -v python3 &> /dev/null; then
    echo "[ERROR] python3 not found. Please install it first (see README)."
    exit 1
fi

echo "[Kai Setup] Creating virtual environment..."
python3 -m venv "$VENV_DIR"

if [ ! -f "$VENV_DIR/bin/python" ]; then
    echo "[ERROR] venv creation failed: $VENV_DIR/bin/python does not exist."
    echo "Check the python3 -m venv output above for the actual error."
    exit 1
fi

echo "[Kai Setup] venv created OK. Installing dependencies..."
source "$VENV_DIR/bin/activate"

# Mirror index in case pypi.org is slow/unreachable on this network.
# If this mirror is also flaky, try:
#   https://mirrors.aliyun.com/pypi/simple/  (host: mirrors.aliyun.com)
PIP_INDEX="https://pypi.tuna.tsinghua.edu.cn/simple"
PIP_HOST="pypi.tuna.tsinghua.edu.cn"

pip install --upgrade pip -i "$PIP_INDEX" --trusted-host "$PIP_HOST"
pip install -r "$PROJECT_DIR/requirements.txt" -i "$PIP_INDEX" --trusted-host "$PIP_HOST"
if [ $? -ne 0 ]; then
    echo "[ERROR] Core dependencies failed to install, see errors above."
    exit 1
fi

echo ""
echo "[Kai Setup] Installing offline model support (llama-cpp-python)..."
echo "This is OPTIONAL - only needed for the no-internet fallback model."
pip install llama-cpp-python --prefer-binary -i "$PIP_INDEX" --trusted-host "$PIP_HOST"
if [ $? -ne 0 ]; then
    echo "[WARNING] llama-cpp-python install failed - offline fallback model will"
    echo "NOT be available, but Kai still works fully in online mode."
    echo "On Mac this usually needs Xcode command line tools (xcode-select --install)."
    echo "On Linux this usually needs a C compiler (e.g. sudo apt install build-essential)."
else
    echo "[Kai Setup] Offline model support installed OK."
fi

echo ""
echo "[Kai Setup] Bootstrapping default offline fallback model (~1GB, one time)..."
echo "This guarantees Kai has basic reasoning ability even with zero online providers configured."
pip install huggingface_hub -i "$PIP_INDEX" --trusted-host "$PIP_HOST" -q
python3 "$SCRIPT_DIR/bootstrap_local_model.py" || echo "[WARNING] Auto-download failed, see message above. Kai still works fully in online mode."

echo "[Kai Setup] Done! Run ./start_kai.sh to launch."

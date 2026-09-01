@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title CosyVoice Environment Setup

:: ====================== 默认选项 ======================
set "SKIP_MODEL_DOWNLOAD=0"
set "DOWNLOAD_FULL_MODELS=0"
set "USE_GITEE_MIRROR=0"
set "RUN_LIST_VOICES=1"

:: ====================== 全局路径配置（统一反斜杠） ======================
set SCRIPT_DIR=%~dp0
set "PROJECT_ROOT=%SCRIPT_DIR%..\.."

set "VENV_DIR=%SCRIPT_DIR%venv"
set "COSYVOICE_REPO_PATH=%SCRIPT_DIR%CosyVoice"
set "PRETRAINED_MODELS_PATH=%SCRIPT_DIR%pretrained_models"
set "BASE_MODEL_DIR=%PRETRAINED_MODELS_PATH%\CosyVoice-300M-SFT"

:: ====================== 交互菜单 ======================
:menu
cls
echo ============================================================
echo         CosyVoice Environment Setup
echo ============================================================
echo.
echo  Configure options before installation:
echo.

:: 显示状态
if %SKIP_MODEL_DOWNLOAD%==1 (set "SM_STATUS=ON") else (set "SM_STATUS=OFF")
if %DOWNLOAD_FULL_MODELS%==1 (set "FM_STATUS=ON") else (set "FM_STATUS=OFF")
if %USE_GITEE_MIRROR%==1 (set "GM_STATUS=ON") else (set "GM_STATUS=OFF")
if %RUN_LIST_VOICES%==1 (set "LV_STATUS=ON") else (set "LV_STATUS=OFF")

echo    [1] Skip pretrained model download     [%SM_STATUS%]
echo    [2] Download all pretrained models     [%FM_STATUS%]
echo    [3] Use Gitee mirror for clone         [%GM_STATUS%]
echo    [4] Run list_voices.py after install   [%LV_STATUS%]
echo.
echo    [5] Start installation
echo    [0] Exit
echo.
set "choice="
set /p "choice=Please enter option number: "

if "%choice%"=="1" (
    if %SKIP_MODEL_DOWNLOAD%==0 (set "SKIP_MODEL_DOWNLOAD=1") else (set "SKIP_MODEL_DOWNLOAD=0")
    goto menu
)
if "%choice%"=="2" (
    if %DOWNLOAD_FULL_MODELS%==0 (set "DOWNLOAD_FULL_MODELS=1") else (set "DOWNLOAD_FULL_MODELS=0")
    goto menu
)
if "%choice%"=="3" (
    if %USE_GITEE_MIRROR%==0 (set "USE_GITEE_MIRROR=1") else (set "USE_GITEE_MIRROR=0")
    goto menu
)
if "%choice%"=="4" (
    if %RUN_LIST_VOICES%==0 (set "RUN_LIST_VOICES=1") else (set "RUN_LIST_VOICES=0")
    goto menu
)
if "%choice%"=="5" goto start_install
if "%choice%"=="0" (
    endlocal
    exit /b 0
)

echo Invalid option, please try again.
pause >nul
goto menu

:: ====================== 主安装流程 ======================
:start_install
cls

echo ============================================================
echo         CosyVoice Environment Setup and Installation
echo ============================================================
echo [+] Project root: %PROJECT_ROOT%
echo [+] Virtual env path: %VENV_DIR%
echo [+] Repository path: %COSYVOICE_REPO_PATH%
echo [+] Model storage path: %PRETRAINED_MODELS_PATH%
echo.
if %USE_GITEE_MIRROR%==1 echo [INFO] Gitee mirror enabled
if %SKIP_MODEL_DOWNLOAD%==1 echo [INFO] Model download skipped
if %DOWNLOAD_FULL_MODELS%==1 echo [INFO] Full models will be downloaded
if %RUN_LIST_VOICES%==1 echo [INFO] list_voices.py will run after installation
if %RUN_LIST_VOICES%==0 echo [INFO] list_voices.py execution disabled
echo.

:: ---------------------- Step 1: 系统依赖检查 ----------------------
echo [1/7] Checking system dependencies...

call conda --version >nul 2>&1
call :check_result "Conda detection"

call git --version >nul 2>&1
call :check_result "Git detection"

echo.

:: ---------------------- Step 2: 克隆仓库 ----------------------
echo [2/7] Processing CosyVoice repository...

if exist "%COSYVOICE_REPO_PATH%" (
    echo [INFO] Repository already exists, clone skipped.
) else (
    if %USE_GITEE_MIRROR%==1 (
        set "REPO_URL=shturl.cc/Oyuh2j83D67uD9BnJInYPJdIMoclP"
    ) else (
        set "REPO_URL=https://github.com/FunAudioLLM/CosyVoice.git"
    )
    echo [+] Cloning repository: !REPO_URL!
	REM 子模块可能clone失败，最好在对应目录下手动git：
	REM git clone https://github.com/shivammehta25/Matcha-TTS.git
    git clone --recursive "!REPO_URL!" "%COSYVOICE_REPO_PATH%"
    call :check_result "Repository clone"
)
echo.

:: ---------------------- Step 3: 创建虚拟环境 ----------------------
echo [3/7] Creating Python 3.11 virtual environment...

if exist "%VENV_DIR%" (
    echo [INFO] Virtual environment already exists, creation skipped
) else (
    echo [+] Creating isolated venv at: %VENV_DIR%
    call conda create --prefix "%VENV_DIR%" python=3.11 -y
    call :check_result "Virtual environment creation"
)
echo.

:: ---------------------- Step 4: 激活虚拟环境 ----------------------
echo [4/7] Activating virtual environment...

call conda.bat activate "%VENV_DIR%"
call :check_result "Virtual environment activation"
python --version
for /f "delims=" %%i in ('python --version 2^>^&1') do set "PY_VER=%%i"
echo [INFO] Current Python version: %PY_VER%
echo.
python -c "import sys; print(sys.executable)" 

:: ---------------------- Step 5: 安装依赖 ----------------------
echo [5/7] Installing core dependencies...

pip --version
echo [+] Configuring PyPI mirror
pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/
pip config set install.trusted-host mirrors.aliyun.com




echo [+] Installing pynini==2.1.5 from conda-forge

call conda install pynini==2.1.5
REM call conda install -y -c conda-forge pynini==2.1.5
REM call conda install -y -c https://mirrors.aliyun.com/anaconda/cloud/conda-forge/ pynini==2.1.5

call :check_result "pynini installation"

:: requirements.txt Download
echo %SCRIPT_DIR%requirements.txt
if exist "%SCRIPT_DIR%requirements.txt" (
    echo [+] Installing custom project requirements
    pip install -r "%SCRIPT_DIR%requirements.txt"
    call :check_result "Custom dependencies installation"
) else (
    echo [WARN] requirements.txt not found, verify repository integrity
)

echo %COSYVOICE_REPO_PATH%\requirements.txt
if exist "%COSYVOICE_REPO_PATH%\requirements.txt" (
    echo [+] Installing CosyVoice official requirements
    pip install --no-cache-dir --index-url https://mirrors.aliyun.com/pypi/simple/ -r "%COSYVOICE_REPO_PATH%\requirements.txt"
    call :check_result "Official dependencies installation"
) else (
    echo [WARN] CosyVoice/requirements.txt not found, verify repository integrity
)
echo.

:: ---------------------- Step 6: 下载预训练模型 ----------------------
echo [6/7] Downloading pretrained models...

if %SKIP_MODEL_DOWNLOAD%==1 (
    echo [INFO] Model download skipped by option
    goto skip_model_download
)

if not exist "%PRETRAINED_MODELS_PATH%" mkdir "%PRETRAINED_MODELS_PATH%"

echo [+] Installing modelscope download tool
pip install modelscope
call :check_result "modelscope installation"

:: 将 Windows 反斜杠转为正斜杠供 Python 使用
set "MODEL_PATH_POSIX=%PRETRAINED_MODELS_PATH:\=/%"

:: 下载基础模型（若已存在则跳过）
if exist "%BASE_MODEL_DIR%" (
    echo [INFO] CosyVoice-300M-SFT model already exists, download skipped
) else (
    echo [+] Downloading CosyVoice-300M-SFT model
    python -c "from modelscope import snapshot_download; snapshot_download('iic/CosyVoice-300M-SFT', local_dir='%MODEL_PATH_POSIX%/CosyVoice-300M-SFT')"
    call :check_result "Base model download"
)

:: 下载完整模型集合（每个模型独立检查）
if %DOWNLOAD_FULL_MODELS%==1 (
    echo [+] Processing full pretrained model set

    if exist "%PRETRAINED_MODELS_PATH%\Fun-CosyVoice3-0.5B" (
        echo [INFO] Fun-CosyVoice3-0.5B already exists, skipped
    ) else (
        python -c "from modelscope import snapshot_download; snapshot_download('FunAudioLLM/Fun-CosyVoice3-0.5B-2512', local_dir='%MODEL_PATH_POSIX%/Fun-CosyVoice3-0.5B')"
        call :check_result "CosyVoice3-0.5B model download"
    )

    if exist "%PRETRAINED_MODELS_PATH%\CosyVoice2-0.5B" (
        echo [INFO] CosyVoice2-0.5B already exists, skipped
    ) else (
        python -c "from modelscope import snapshot_download; snapshot_download('iic/CosyVoice2-0.5B', local_dir='%MODEL_PATH_POSIX%/CosyVoice2-0.5B')"
        call :check_result "CosyVoice2-0.5B model download"
    )

    if exist "%PRETRAINED_MODELS_PATH%\CosyVoice-300M" (
        echo [INFO] CosyVoice-300M already exists, skipped
    ) else (
        python -c "from modelscope import snapshot_download; snapshot_download('iic/CosyVoice-300M', local_dir='%MODEL_PATH_POSIX%/CosyVoice-300M')"
        call :check_result "CosyVoice-300M model download"
    )

    if exist "%PRETRAINED_MODELS_PATH%\CosyVoice-300M-Instruct" (
        echo [INFO] CosyVoice-300M-Instruct already exists, skipped
    ) else (
        python -c "from modelscope import snapshot_download; snapshot_download('iic/CosyVoice-300M-Instruct', local_dir='%MODEL_PATH_POSIX%/CosyVoice-300M-Instruct')"
        call :check_result "300M-Instruct model download"
    )

    if exist "%PRETRAINED_MODELS_PATH%\CosyVoice-ttsfrd" (
        echo [INFO] CosyVoice-ttsfrd already exists, skipped
    ) else (
        python -c "from modelscope import snapshot_download; snapshot_download('iic/CosyVoice-ttsfrd', local_dir='%MODEL_PATH_POSIX%/CosyVoice-ttsfrd')"
        call :check_result "ttsfrd model download"
    )
)

:skip_model_download
echo.

:: ---------------------- Step 7: 验证与收尾 ----------------------
echo [7/7] Environment verification and finalization...

echo [+] Verifying core package imports
call python -c "import torch; import cosyvoice" 2>nul
if %errorlevel% neq 0 (
    echo [WARN] Core package import verification failed
) else (
    echo [OK] Core dependency import verification passed
)

if %RUN_LIST_VOICES%==1 (
    if exist "%SCRIPT_DIR%list_voices.py" (
        echo [+] Running voice list query
        python "%SCRIPT_DIR%list_voices.py"
    ) else (
        echo [INFO] list_voices.py not found, skipped
    )
) else (
    echo [INFO] list_voices.py execution disabled by option
)

echo.
echo ============================================================
echo         SUCCESS: CosyVoice environment setup completed!
echo ============================================================
echo  Virtual Environment: %VENV_DIR%
echo  Code Repository: %COSYVOICE_REPO_PATH%
echo  Model Directory: %PRETRAINED_MODELS_PATH%
echo.
echo  Activate command: conda activate "%VENV_DIR%"
echo ============================================================

pause
endlocal
exit /b 0

:: ====================== 辅助函数 ======================
:check_result
if %errorlevel% neq 0 (
    echo [ERROR] %~1 failed, error code: %errorlevel%
    echo.
    pause
    exit /b %errorlevel%
)
echo [OK] %~1 succeeded
goto :eof
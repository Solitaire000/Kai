@echo off
REM First-time setup on a new Windows PC. Uses %~dp0 so it works regardless of drive letter.

set SCRIPT_DIR=%~dp0
set PROJECT_DIR=%SCRIPT_DIR%..
set VENV_DIR=%PROJECT_DIR%\venv

echo [Kai Setup] Project dir: %PROJECT_DIR%

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found on this PC.
    echo See README.md "fully portable option" section for embeddable Python.
    pause
    exit /b 1
)

echo [Kai Setup] Found python at:
where python
echo [Kai Setup] Python version:
python --version
if errorlevel 1 (
    echo [ERROR] "python --version" failed.
    echo This usually means "python" is the Windows Store alias, not a real Python install.
    echo Fix: install real Python from python.org/downloads/windows
    echo   ^(check "Add python.exe to PATH" during install^), then rerun this script.
    pause
    exit /b 1
)

echo [Kai Setup] Creating virtual environment...
python -m venv "%VENV_DIR%"

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo.
    echo [ERROR] venv creation failed: %VENV_DIR%\Scripts\python.exe does not exist.
    echo Most common cause: "python" points to the Windows Store alias instead of real Python.
    echo Fix:
    echo   1. Settings - Apps - Advanced app settings - App execution aliases
    echo      turn OFF python.exe / python3.exe
    echo   2. Install real Python from python.org/downloads/windows ^(check Add to PATH^)
    echo   3. Rerun this script
    pause
    exit /b 1
)

echo [Kai Setup] venv created OK. Installing dependencies, this may take a few minutes...
call "%VENV_DIR%\Scripts\activate.bat"
REM cmd /k


REM Clear any broken proxy env vars for this session only (does not touch
REM your system-wide proxy settings). A leftover/broken proxy config
REM (e.g. from VPN software) is a common cause of install failures.
set HTTP_PROXY=
set HTTPS_PROXY=
set ALL_PROXY=
set http_proxy=
set https_proxy=
set all_proxy=

REM Using Tsinghua mirror instead of pypi.org directly.
REM Connecting straight to pypi.org from mainland China networks often fails with
REM SSL errors (blocked/unstable route). If Tsinghua is also flaky, try:
REM   https://mirrors.aliyun.com/pypi/simple/  (host: mirrors.aliyun.com)
set PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
set PIP_HOST=pypi.tuna.tsinghua.edu.cn

python -m pip install --upgrade pip -i %PIP_INDEX% --trusted-host %PIP_HOST%
pip install -r "requirements.txt" -i %PIP_INDEX% --trusted-host %PIP_HOST%
if errorlevel 1 (
    echo [ERROR] Core dependencies failed to install, see the errors above.
    echo Common causes: SSL/proxy issues, or antivirus HTTPS inspection.
    pause
    exit /b 1
)

echo.
echo [Kai Setup] Installing offline model support (llama-cpp-python)...
echo This is OPTIONAL - only needed for the no-internet fallback model.
echo Using prebuilt wheels so no C++ compiler or long-path issues.
pip install llama-cpp-python --prefer-binary ^
    --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu ^
    -i %PIP_INDEX% --trusted-host %PIP_HOST%
if errorlevel 1 (
    echo.
    echo [WARNING] llama-cpp-python install failed - offline fallback model will
    echo NOT be available, but Kai still works fully in online mode.
    echo You can retry later by running this in the venv:
    echo   pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
) else (
    echo [Kai Setup] Offline model support installed OK.
)

echo.
echo [Kai Setup] Bootstrapping default offline fallback model (~1GB, one time)...
echo This guarantees Kai has basic reasoning ability even with zero online providers configured.
pip install huggingface_hub -i %PIP_INDEX% --trusted-host %PIP_HOST% -q
python "%~dp0bootstrap_local_model.py"
if errorlevel 1 (
    echo [WARNING] Auto-download failed, see message above. Kai still works fully in online mode.
)

echo [Kai Setup] Done! From now on just double-click start_kai.bat
pause

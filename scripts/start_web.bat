@echo off
setlocal enabledelayedexpansion

REM ===================================================================
REM 定位项目根目录
REM ===================================================================
set "SCRIPT_DIR=%~dp0"
set "PROJECT_DIR=%SCRIPT_DIR%.."
pushd "%PROJECT_DIR%" || (
    echo [ERROR] Failed to switch to project directory: %PROJECT_DIR%
    pause
    exit /b 1
)

REM conda 环境
set "PYTHON_SCRIPT=web_app.py"
set "COSY_DIR=%PROJECT_DIR%\voice\CosyVoice"
set "COSY_VENV=venv"
set "COSY_SCRIPT=tts_server.py"

REM 普通虚拟环境
set "MAIN_VENV_ACTIVATE=%PROJECT_DIR%\venv\Scripts\activate.bat"
set "FOUND_MAIN_ENV=0"

REM ===================================================================
REM 1. 先启动 CosyVoice TTS 服务（独立新窗口，独立venv，不影响主流程）
REM ===================================================================
if exist "%COSY_DIR%\venv" (
    if exist "%COSY_DIR%\%COSY_SCRIPT%" (
        echo [Kai] Found CosyVoice venv, launching TTS server in new window...
		echo %COSY_DIR%
        REM 新窗口内部：cd到CosyVoice目录 -> 激活它自己的venv -> 启动tts_server.py
        start "CosyVoice TTS Server" cmd /k "cd /d "%COSY_DIR%" &&  call conda activate "%COSY_DIR%\venv" && python "%COSY_SCRIPT%""
        REM start "CosyVoice TTS Server" cmd /k "cd /d "%COSY_DIR%" &&  call conda activate "%COSY_DIR%\venv" && python "%COSY_SCRIPT%""
		REM start /min "CosyVoice TTS Server" cmd /k "cd /d "%COSY_DIR%" && call "%COSY_VENV_ACTIVATE%" && python "%COSY_SCRIPT%""
		
    ) else (
        echo [WARN] tts_server.py not found at %COSY_DIR%, skipping TTS server.
    )
) else (
    echo [WARN] CosyVoice venv not found at %COSY_DIR%\venv, skipping TTS server.
    echo        Voice features will be unavailable. Run voice\CosyVoice\setup_env.bat to fix.
)

REM ===================================================================
REM 2. 激活主venv，启动主程序 web_app.py（当前窗口）
REM ===================================================================
if exist "%MAIN_VENV_ACTIVATE%" (
    echo [Kai] Found standard venv, activating...
    call "%MAIN_VENV_ACTIVATE%"
    if errorlevel 1 (
        echo [ERROR] venv activation failed. Please check if the environment is complete.
        pause
        exit /b 1
    )
    set "FOUND_MAIN_ENV=1"
) else (
    echo [ERROR] Main venv not found at %PROJECT_DIR%\venv
    echo         Please run setup_env.bat first to create the environment.
    pause
    exit /b 1
)

REM ===================================================================
REM 3. 运行主脚本
REM ===================================================================
:run_script
echo [Kai] Starting %PYTHON_SCRIPT% ...
python "%PYTHON_SCRIPT%"
set "EXIT_CODE=%errorlevel%"

if %EXIT_CODE% neq 0 (
    echo [Kai] %PYTHON_SCRIPT% exited abnormally with return code: %EXIT_CODE%
) else (
    echo [Kai] %PYTHON_SCRIPT% terminated normally.
)

echo.
echo Press any key to exit...
pause >nul

popd
exit /b %EXIT_CODE%
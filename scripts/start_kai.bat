@echo off
set SCRIPT_DIR=%~dp0
set PROJECT_DIR=%SCRIPT_DIR%..
set VENV_DIR=%PROJECT_DIR%\venv
set EMBED_DIR=%PROJECT_DIR%\python_embed

cd /d "%PROJECT_DIR%"

if exist "%EMBED_DIR%\python.exe" (
    "%EMBED_DIR%\python.exe" main.py
    pause
    exit /b 0
)

if exist "%VENV_DIR%\Scripts\activate.bat" (
    call "%VENV_DIR%\Scripts\activate.bat"
    python main.py
    pause
    exit /b 0
)

echo [Kai] 没找到 venv 或 python_embed。
echo   普通电脑: 先运行 setup_env.bat
echo   没装Python的电脑: 先运行 setup_embed_windows.bat
pause

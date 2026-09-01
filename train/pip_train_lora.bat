@echo off
chcp 65001 >nul
setlocal

:: ==========================
:: Python
:: ==========================
set PYTHON=python

echo.
echo ==========================
echo      Kai LoRA Trainer
echo ==========================
echo.

:: ==========================
:: 安装训练依赖
:: ==========================
echo Checking training dependencies...
%PYTHON% -m pip install -r requirements-train.txt
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to install training dependencies.
    pause
    exit /b 1
)

echo.
set PARAMS=

set /p DRY=Dry Run? (Y/N):
if /I "%DRY%"=="Y" (
    set PARAMS=%PARAMS% --dry-run
)

set /p USED=Include Used Samples? (Y/N):
if /I "%USED%"=="Y" (
    set PARAMS=%PARAMS% --include-used
)

echo.
echo Starting LoRA training...
echo.

%PYTHON% train_lora.py %PARAMS%

echo.
pause
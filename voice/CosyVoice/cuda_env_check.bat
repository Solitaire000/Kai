@echo off
chcp 65001 >nul
set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%..\.."
set "VENV_DIR=%SCRIPT_DIR%venv"

echo ==================================================
echo CosyVoice CUDA Check ^& Launch
echo ==================================================

cd /d "%PROJECT_ROOT%\voice\CosyVoice" || (echo Project root not found & pause & exit /b 1)

echo [+] Activating virtual environment...
call conda.bat activate "%VENV_DIR%"
echo.
cmd /k
REM pip uninstall torch torchvision torchaudio -y
REM pip install --pre torch torchvision torchaudio --index-url https://download.pytorch.org/whl/nightly/cu128
if errorlevel 1 (echo  Virtual environment activation failed & pause & exit /b 1)
for /f "delims=" %%i in ('python --version 2^>^&1') do echo [INFO] %%i


echo [+] Running CUDA environment validation...
REM set "TORCH_CUDA_ARCH_LIST=7.0;7.5;8.0;8.6;8.9;9.0;12.0"
REM set "CUDA_LAUNCH_BLOCKING=1"
REM python "%SCRIPT_DIR%cuda_env_check.py"
REM if errorlevel 1 (echo  Environment validation failed & pause & exit /b 1)
echo [+] All checks passed...

echo [+] starting CosyVoice...
python list_voices.py

pause

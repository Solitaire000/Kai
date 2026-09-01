@echo off
chcp 65001 >nul
setlocal

set PYTHON=python

echo.
echo ===============================
echo   Compare Adapter Versions
echo ===============================
echo.

set /p OLD=Old Version (例如 v1，直接回车表示自动):
set /p NEW=New Version (例如 v5，直接回车表示自动):

if "%OLD%"=="" (
    if "%NEW%"=="" (
        %PYTHON% compare_adapter_versions.py
        goto END
    )
)

%PYTHON% compare_adapter_versions.py --a %OLD% --b %NEW%

:END
echo.
pause
@echo off
REM ============================================================
REM Set up Windows embeddable Python (fully portable, no install needed).
REM Only needed when this PC has NO Python at all / no install rights.
REM Otherwise prefer setup_env.bat (venv) - simpler and easier to maintain.
REM
REM What this script does:
REM   1. Download the python.org embeddable zip and extract to python_embed\
REM   2. Download get-pip.py and install pip into it
REM   3. Edit the ._pth file to uncomment "import site" (required for pip
REM      installed packages to be importable)
REM   4. Install project dependencies using this portable python
REM
REM Needs direct access to python.org and pypi.org. If you normally need a
REM proxy/VPN to reach sites outside China, turn it on before running this
REM script - there is no domestic mirror for python.org itself.
REM ============================================================
setlocal enabledelayedexpansion

set SCRIPT_DIR=%~dp0
set PROJECT_DIR=%SCRIPT_DIR%..
set EMBED_DIR=%PROJECT_DIR%\python_embed
set PY_VERSION=3.11.9
set PY_ZIP_URL=https://www.python.org/ftp/python/%PY_VERSION%/python-%PY_VERSION%-embed-amd64.zip
set GET_PIP_URL=https://bootstrap.pypa.io/get-pip.py

echo [Kai] Target dir: %EMBED_DIR%
echo [Kai] Will download Python %PY_VERSION% embeddable

if exist "%EMBED_DIR%\python.exe" (
    echo [Kai] python_embed already set up, skipping download.
    echo       Delete the python_embed folder first if you want to redo this.
    goto :install_deps
)

mkdir "%EMBED_DIR%" 2>nul

echo [Kai] Downloading: %PY_ZIP_URL%
powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri '%PY_ZIP_URL%' -OutFile '%EMBED_DIR%\python-embed.zip'"
if errorlevel 1 (
    echo [ERROR] Download failed. Check whether this network/proxy can reach python.org
    echo You can also manually download from python.org/downloads/windows,
    echo extract it into %EMBED_DIR%, then rerun this script.
    pause
    exit /b 1
)

echo [Kai] Extracting...
powershell -Command "Expand-Archive -Path '%EMBED_DIR%\python-embed.zip' -DestinationPath '%EMBED_DIR%' -Force"
if errorlevel 1 (
    echo [ERROR] Extraction failed. The downloaded zip may be corrupted/incomplete.
    echo Delete %EMBED_DIR%\python-embed.zip and rerun this script.
    pause
    exit /b 1
)
if not exist "%EMBED_DIR%\python.exe" (
    echo [ERROR] python.exe not found after extraction. Something went wrong.
    pause
    exit /b 1
)
del "%EMBED_DIR%\python-embed.zip"

echo [Kai] Downloading get-pip.py and installing pip...
powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri '%GET_PIP_URL%' -OutFile '%EMBED_DIR%\get-pip.py'"
if errorlevel 1 (
    echo [ERROR] Failed to download get-pip.py. Check network/proxy access to pypi.org.
    pause
    exit /b 1
)

"%EMBED_DIR%\python.exe" "%EMBED_DIR%\get-pip.py"
if errorlevel 1 (
    echo [ERROR] pip installation into python_embed failed, see errors above.
    pause
    exit /b 1
)
if not exist "%EMBED_DIR%\Scripts\pip.exe" (
    echo [ERROR] pip.exe not found after get-pip.py ran. Something went wrong.
    pause
    exit /b 1
)

echo [Kai] Patching ._pth file to enable site-packages (needed for pip installed packages to work)...
for %%f in ("%EMBED_DIR%\python3*._pth") do (
    powershell -Command "(Get-Content '%%f') -replace '#import site', 'import site' | Set-Content '%%f'"
)

:install_deps
echo [Kai] Installing project dependencies with the portable python...
set PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
set PIP_HOST=pypi.tuna.tsinghua.edu.cn

"%EMBED_DIR%\python.exe" -m pip install -r "%PROJECT_DIR%\requirements.txt" -i %PIP_INDEX% --trusted-host %PIP_HOST%
if errorlevel 1 (
    echo [ERROR] Dependency install failed, see errors above.
    pause
    exit /b 1
)

echo [Kai] Installing offline local model support (llama-cpp-python, optional -
echo       failure here does not affect online mode)...

set LLAMA_OK=0

REM Attempt 1-3: prebuilt wheel from abetlen's index (GitHub Pages, can be
REM flaky/interrupted on some networks - retry with cache purge each time).
for /L %%i in (1,1,3) do (
    if "!LLAMA_OK!"=="0" (
        echo [Kai] Attempt %%i/3: abetlen wheel index...
        "%EMBED_DIR%\python.exe" -m pip cache purge >nul 2>nul
        "%EMBED_DIR%\python.exe" -m pip install llama-cpp-python --prefer-binary ^
            --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu ^
            -i %PIP_INDEX% --trusted-host %PIP_HOST% --timeout 60
        if not errorlevel 1 (
            set LLAMA_OK=1
        ) else (
            echo [Kai] Attempt %%i failed ^(likely a truncated/corrupted download^), retrying...
            timeout /t 3 >nul
        )
    )
)

REM Fallback: some llama-cpp-python versions also publish wheels straight to
REM PyPI, try that in case the abetlen index is unreachable from this network.
if "!LLAMA_OK!"=="0" (
    echo [Kai] abetlen index failed after 3 tries, trying plain PyPI mirror as fallback...
    "%EMBED_DIR%\python.exe" -m pip cache purge >nul 2>nul
    "%EMBED_DIR%\python.exe" -m pip install llama-cpp-python --prefer-binary ^
        -i %PIP_INDEX% --trusted-host %PIP_HOST% --timeout 60
    if not errorlevel 1 (
        set LLAMA_OK=1
    )
)

if "!LLAMA_OK!"=="0" (
    echo.
    echo [WARNING] Could not install llama-cpp-python after multiple attempts and
    echo sources - offline fallback model will NOT be available, but Kai still
    echo works fully in online mode.
    echo.
    echo To install it manually later:
    echo   1. Open https://abetlen.github.io/llama-cpp-python/whl/cpu/ in a browser
    echo      and download the matching .whl file yourself ^(browser downloads
    echo      resume better than pip's http client on unstable connections^)
    echo   2. Then run:
    echo      python_embed\python.exe -m pip install C:\path\to\downloaded.whl
) else (
    echo [Kai] Offline model support installed OK.
)

echo.
echo [Kai] Done! You can now start Kai without installing anything else on this PC:
echo   CLI:  python_embed\python.exe main.py
echo   Web:  python_embed\python.exe web_app.py
echo   Or just double-click scripts\start_kai.bat / scripts\start_web.bat
echo   (they auto-detect python_embed)
pause

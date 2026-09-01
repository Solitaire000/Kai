@echo off
setlocal enabledelayedexpansion

:: ==============================================================================
:: Base Model Migration Batch Script
:: Automates and guides the process of migrating to a new base model.
:: ==============================================================================

:: Change working directory to the parent directory of this script (project root)
cd /d "%~dp0"

echo ==============================================================================
echo Base Model Migration Workflow
echo ==============================================================================
echo.
echo Select execution mode:
echo   [1] Run Full Workflow (Step 1 -^> Manual Config Update -^> Steps 3-5)
echo   [2] Step 1: Probe/Snapshot Old Brain (distill-old)
echo   [3] Step 3: Refine Corpus Only (refine)
echo   [4] Steps 3-5: Train and Check (train-and-check)
echo   [5] Exit
echo.

set /p MODE="Enter choice [1-5]: "

if "%MODE%"=="1" goto MODE_ALL
if "%MODE%"=="2" goto MODE_DISTILL
if "%MODE%"=="3" goto MODE_REFINE
if "%MODE%"=="4" goto MODE_TRAIN_CHECK
if "%MODE%"=="5" goto END
echo Invalid choice. Exiting.
goto END

:MODE_ALL
echo.
echo --- Mode 1: Full Migration Workflow ---
set /p LABEL="Enter snapshot label (e.g., before_switch_2026q3): "
if "%LABEL%"=="" (
    echo [ERROR] Label cannot be empty.
    goto END
)
set /p PROVIDER="Enter provider or press Enter for default/local [e.g., local]: "

if not "%PROVIDER%"=="" (
    python migrate_base_model.py --step all --label "%LABEL%" --provider "%PROVIDER%"
) else (
    python migrate_base_model.py --step all --label "%LABEL%"
)
goto END

:MODE_DISTILL
echo.
echo --- Mode 2: Snapshot Old Brain (distill-old) ---
set /p LABEL="Enter snapshot label (e.g., before_switch_2026q3): "
if "%LABEL%"=="" (
    echo [ERROR] Label cannot be empty.
    goto END
)
set /p PROVIDER="Enter provider or press Enter for default/local [e.g., local]: "

if not "%PROVIDER%"=="" (
    python migrate_base_model.py --step distill-old --label "%LABEL%" --provider "%PROVIDER%"
) else (
    python migrate_base_model.py --step distill-old --label "%LABEL%"
)
echo.
echo [NEXT STEP] Edit config/config.yaml -^> training.lora.base_model to point to your NEW model.
echo Then run this batch file again and select choice [4] (train-and-check).
goto END

:MODE_REFINE
echo.
echo --- Mode 3: Refine Corpus Only (refine) ---
python migrate_base_model.py --step refine
goto END

:MODE_TRAIN_CHECK
echo.
echo --- Mode 4: Train and Check (train-and-check) ---
set /p SKIP_REFINE="Skip corpus refinement? (y/N): "
if /i "%SKIP_REFINE%"=="y" (
    python migrate_base_model.py --step train-and-check --skip-refine
) else (
    python migrate_base_model.py --step train-and-check
)
goto END

:END
echo.
echo Process finished.
pause
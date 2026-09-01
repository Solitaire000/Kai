@echo off
setlocal EnableDelayedExpansion

title Model Migration Control Panel

cd /d "%~dp0"

echo =====================================================
echo              Model Migration Control
echo =====================================================

:MENU

echo.
echo Select operation:
echo.
echo [1] List agents
echo [2] Self distillation
echo [3] Distill training corpus
echo [4] Base model migration pipeline
echo [5] Regression score
echo [0] Exit
echo.

set /p CHOICE=Select:


if "%CHOICE%"=="1" goto LIST_AGENT
if "%CHOICE%"=="2" goto SELF_DISTILL
if "%CHOICE%"=="3" goto DISTILL_CORPUS
if "%CHOICE%"=="4" goto MIGRATE_BASE
if "%CHOICE%"=="5" goto REGRESSION
if "%CHOICE%"=="0" goto EXIT

goto MENU



:LIST_AGENT

echo.
python migrate_base_model.py --list-agents

pause
goto MENU



:SELF_DISTILL

echo.
echo ==============================
echo Self Distillation
echo ==============================

echo Mode:
echo [1] Provider mode
echo [2] Adapter mode

set /p MODE=Select:

set /p LABEL=Snapshot label:

if "%MODE%"=="1" (

    set /p PROVIDER=Provider name:

    set CMD=python self_distillation.py --provider !PROVIDER! --label !LABEL!


    echo Include subagents?
    echo [Y] Yes
    echo [N] No

    set /p SUB=

    if /i "!SUB!"=="Y" (
        set CMD=!CMD! --include-subagents
    )


) else (

    set /p ADAPTER=Adapter path:

    set /p BASEMODEL=Old base model:

    set CMD=python self_distillation.py --adapter-path "!ADAPTER!" --base-model "!BASEMODEL!" --label !LABEL!

)


echo.
echo Execute:
echo !CMD!

call !CMD!

pause
goto MENU




:DISTILL_CORPUS

echo.
echo ==============================
echo Corpus Distillation
echo ==============================


set CMD=python distill_training_corpus.py


set /p AGENT=Agent name(optional):

if not "!AGENT!"=="" (
    set CMD=!CMD! --agent !AGENT!
)


set /p BATCH=Batch size(default 20):

if not "!BATCH!"=="" (
    set CMD=!CMD! --batch-size !BATCH!
)


echo Dry run?
echo [Y/N]

set /p DRY=

if /i "!DRY!"=="Y" (
    set CMD=!CMD! --dry-run
)


set /p PROVIDER=Provider(optional):

if not "!PROVIDER!"=="" (
    set CMD=!CMD! --provider !PROVIDER!
)


echo.
echo Execute:
echo !CMD!

call !CMD!

pause
goto MENU





:MIGRATE_BASE

echo.
echo ==============================
echo Base Model Migration
echo ==============================


echo Step:
echo [1] distill-old
echo [2] refine
echo [3] train-and-check
echo [4] all

set /p STEP=Select:


if "%STEP%"=="1" set STEP_NAME=distill-old
if "%STEP%"=="2" set STEP_NAME=refine
if "%STEP%"=="3" set STEP_NAME=train-and-check
if "%STEP%"=="4" set STEP_NAME=all


set CMD=python migrate_base_model.py --step !STEP_NAME!


if "%STEP_NAME%"=="distill-old" (

    set /p LABEL=Snapshot label:

    set CMD=!CMD! --label !LABEL!


    echo Provider mode?
    echo [Y/N]

    set /p PMODE:


    if /i "!PMODE!"=="Y" (

        set /p PROVIDER=Provider:

        set CMD=!CMD! --provider !PROVIDER!

    ) else (

        set /p ADAPTER=Adapter path:

        set /p BASEOLD=Old base model:

        set CMD=!CMD! --adapter-path "!ADAPTER!" --base-model-old "!BASEOLD!"

    )


    echo Include subagents?
    echo [Y/N]

    set /p INCLUDE:


    if /i "!INCLUDE!"=="Y" (

        set CMD=!CMD! --include-subagents

    )


)



if "%STEP_NAME%"=="train-and-check" (

    echo Skip refine?
    echo [Y/N]

    set /p SKIP:

    if /i "!SKIP!"=="Y" (
        set CMD=!CMD! --skip-refine
    )

)



if "%STEP_NAME%"=="all" (

    set /p LABEL=Snapshot label:

    set CMD=!CMD! --label !LABEL!


    set /p PROVIDER=Provider:

    set CMD=!CMD! --provider !PROVIDER!

)



echo.
echo Execute:
echo !CMD!

call !CMD!

pause
goto MENU






:REGRESSION

echo.
echo ==============================
echo Regression Check
echo ==============================


set /p VERSION=Version:

set CMD=python regression_score.py --version !VERSION!


set /p BASESLUG=Base model slug(optional):

if not "!BASESLUG!"=="" (
    set CMD=!CMD! --base-model-slug !BASESLUG!
)


echo.
echo Execute:
echo !CMD!

call !CMD!


pause
goto MENU





:EXIT

echo Exit.
exit /b 0
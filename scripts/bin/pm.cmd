@echo off
rem pm shim (§9.3, Windows) — %~dp0 기준 ROOT 계산 + PM_HOME 덮어쓰기.
setlocal
set "SELF_DIR=%~dp0"
for %%I in ("%SELF_DIR%..\..") do set "ROOT=%%~fI"
set "PM_HOME=%ROOT%"
set "PYTHONPATH=%ROOT%\scripts;%PYTHONPATH%"

rem 고정 인터프리터(data\env.json) 우선, 없으면 py -3 → python (§9.1)
set "PYBIN="
if exist "%ROOT%\data\env.json" (
    for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command ^
        "(Get-Content '%ROOT%\data\env.json' | ConvertFrom-Json).python"`) do (
        set "PYBIN=%%P"
    )
)
if not defined PYBIN set "PYBIN=py"
if "%PYBIN%"=="py" (
    py -3 -m pm %*
) else (
    "%PYBIN%" -m pm %*
)
endlocal & exit /b %ERRORLEVEL%

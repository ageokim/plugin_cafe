@echo off
rem launcher (Windows — Architecture.md §9·§12.5)
rem ① 멱등 셋업 → ② 부트스트랩 게이트(§9.4 A) → ③ pm serve 백그라운드
rem → ④ 브라우저 오픈. 종료는 브라우저 창 닫기.
setlocal
set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"

rem ── ① 셋업 (§9.3 — 실행 정책 우회 진입) ─────────────────
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\env\setup_win.ps1"
if errorlevel 1 exit /b 1

set "PYBIN="
for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command ^
    "(Get-Content '%ROOT%\data\env.json' | ConvertFrom-Json).python"`) do (
    set "PYBIN=%%P"
)
if not defined PYBIN (
    echo 인터프리터 고정 실패 — env\setup_win.ps1 확인
    exit /b 1
)
set "PYTHONPATH=%ROOT%\scripts;%PYTHONPATH%"

rem ── ② 부트스트랩 게이트 ─────────────────────────────────
"%PYBIN%" -m pm inspect --env --bootstrap
if errorlevel 1 (
    echo.
    echo 위 [FAIL] 항목을 조치한 뒤 run.cmd 를 다시 실행하세요 (§9.4 A^)
    exit /b 1
)

rem ── ③ Flask 백그라운드 + ④ 브라우저 (§12.5) ─────────────
if not defined PM_PORT set "PM_PORT=8765"
start "pm-serve" /b "%PYBIN%" -m pm serve --port %PM_PORT%
timeout /t 2 /nobreak >nul
start "" "http://localhost:%PM_PORT%"
echo 실행 중: http://localhost:%PM_PORT% — 브라우저 창을 닫으면 서버도 자동 종료됩니다
endlocal

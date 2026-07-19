# 멱등 셋업 (Windows — Architecture.md §9.0~9.3)
# run.cmd가 -NoProfile -ExecutionPolicy Bypass 로 호출한다 (§9.3).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$EnvJson = Join-Path $Root "data\env.json"

function Test-Python38([string]$exe) {
    try {
        & $exe -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" 2>$null
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}

function Resolve-Python([string[]]$command) {
    try {
        $resolved = (& $command[0] @($command[1..($command.Length-1)]) `
            -c "import sys; print(sys.executable)" 2>$null)
        if ($resolved) { return "$resolved".Trim() }
    } catch { }
    return $null
}

# ── ① 인터프리터 고정 (§9.1 — Store stub 제외를 위해 py -3 우선) ──
$Py = $null
if (Test-Path $EnvJson) {
    $pinned = (Get-Content $EnvJson -Raw | ConvertFrom-Json).python
    if ($pinned -and (Test-Path $pinned) -and (Test-Python38 $pinned)) {
        $Py = $pinned
        Write-Host "[skip] 인터프리터 이미 고정: $Py"
    }
}
if (-not $Py) {
    foreach ($cand in @(@("py", "-3"), @("python"))) {
        $resolved = Resolve-Python $cand
        if ($resolved -and (Test-Python38 $resolved)) { $Py = $resolved; break }
    }
    if (-not $Py) {
        Write-Host "[fail] python >= 3.8 없음 — winget install Python.Python.3.12"
        exit 1
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $Root "data") | Out-Null
    @{ python = $Py } | ConvertTo-Json | Set-Content -Encoding UTF8 $EnvJson
    Write-Host "[ok]   인터프리터 고정: $Py → data\env.json"
}

# ── ② 의존성 — import 성공 시 pip 자체를 생략 (§9.0·9.2) ──────
$importCheck = @"
import sys
import flask, flask_sock, requests, winpty
if sys.version_info >= (3, 10):
    import claude_agent_sdk
"@
& $Py -c $importCheck 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "[skip] 필수 패키지 이미 충족 — pip 실행 안 함"
} else {
    Write-Host "[..]   pip install --user -r env\requirements.txt"
    & $Py -m pip install --user -r (Join-Path $Root "env\requirements.txt")
    if ($LASTEXITCODE -ne 0) { Write-Host "[fail] 패키지 설치 실패"; exit 1 }
}

# ── ③ pm PATH 등록 — User PATH에 scripts\bin 추가 (§9.3, setx 금지) ──
$BinDir = Join-Path $Root "scripts\bin"
$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (($UserPath -split ";") -contains $BinDir) {
    Write-Host "[skip] pm PATH 이미 등록: $BinDir"
} else {
    # setx는 1024자 절단 버그가 있어 금지 (§9.3)
    [Environment]::SetEnvironmentVariable("Path", "$UserPath;$BinDir", "User")
    Write-Host "[ok]   pm PATH 등록: $BinDir (새 터미널부터 반영)"
}

Write-Host "셋업 완료 (멱등 — 재실행 안전)"
exit 0

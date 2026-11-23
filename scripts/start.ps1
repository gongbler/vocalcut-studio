# Start VocalCut Studio with one command: checks tools, starts backend + frontend
# in the background (skips any that already run), waits until ready, opens the browser.
#
# Usage (from project root):  .\scripts\start.ps1      or double-click  start.cmd
# Stop everything:            .\scripts\stop.ps1       or double-click  stop.cmd
# Server output (for errors): logs\backend.log, logs\frontend.log (+ *.err.log)
#
# Why no server windows? A console window can FREEZE the program inside it:
# one mouse click in a PowerShell window starts 'selection mode' (QuickEdit) and the
# program stops at its next line of output until Enter is pressed. Users saw a blank
# blue window and "server not connected". Background processes writing to log files
# cannot be frozen that way.
#
# NOTE: keep this file ASCII-only. Windows PowerShell 5.1 reads scripts without a BOM
#       as the local code page, so Korean text here would turn into garbage.
param(
    [int]$TimeoutSec = 120,   # how long to wait for the servers to become ready
    [switch]$NoBrowser        # do not open the browser at the end
)
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$BackendUrl = 'http://127.0.0.1:8000/api/health'
$FrontendUrl = 'http://localhost:5173/'
$PidFile = Join-Path $PSScriptRoot '.pids'   # remembered so stop.ps1 can stop exactly these
$LogDir = Join-Path $Root 'logs'

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "    OK  $msg" -ForegroundColor Green }
function Write-Bad($msg)  { Write-Host "    !!  $msg" -ForegroundColor Red }

function Test-Url($url) {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 3
        return $r.StatusCode -eq 200
    } catch { return $false }
}

function Test-PortBusy($port) {
    $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    return $null -ne $c
}

# Start a program hidden, with its output going to log files (new logs every start).
function Start-Server($name, $exe, $arguments, $dir) {
    $out = Join-Path $LogDir "$name.log"
    $err = Join-Path $LogDir "$name.err.log"
    return Start-Process -FilePath $exe -ArgumentList $arguments -WorkingDirectory $dir `
        -WindowStyle Hidden -PassThru -RedirectStandardOutput $out -RedirectStandardError $err
}

function Show-LogTail($name) {
    foreach ($f in "$name.err.log", "$name.log") {
        $path = Join-Path $LogDir $f
        if ((Test-Path $path) -and (Get-Item $path).Length -gt 0) {
            Write-Host "    --- last lines of logs\$f ---" -ForegroundColor Yellow
            Get-Content $path -Tail 12 | ForEach-Object { Write-Host "    $_" }
        }
    }
}

# ---------------------------------------------------------------- 1) tools
Write-Step 'Checking required tools'
$problems = @()
$venvPython = Join-Path $Root 'backend\.venv\Scripts\python.exe'
if (Test-Path $venvPython) { Write-Ok 'Python virtual env (backend\.venv)' }
else { $problems += 'Backend is not installed. Run: .\scripts\setup-backend.ps1' }

$node = Get-Command node -ErrorAction SilentlyContinue
if ($node) { Write-Ok ('Node.js ' + (node --version)) }
else { $problems += 'Node.js not found. Install Node.js 20+ and open a NEW terminal.' }

$viteJs = Join-Path $Root 'frontend\node_modules\vite\bin\vite.js'
if (Test-Path $viteJs) { Write-Ok 'Frontend packages (frontend\node_modules)' }
else { $problems += 'Frontend packages missing. Run: cd frontend; npm.cmd install' }

if (Get-Command ffmpeg -ErrorAction SilentlyContinue) { Write-Ok 'FFmpeg' }
else { $problems += 'FFmpeg not found on PATH. Install it (winget install Gyan.FFmpeg) and open a NEW terminal.' }

if ($problems.Count -gt 0) {
    foreach ($p in $problems) { Write-Bad $p }
    Write-Host ''
    Write-Host 'Fix the items above, then run start again.' -ForegroundColor Yellow
    exit 1
}

# ---------------------------------------------------------------- 2) servers
New-Item -ItemType Directory -Force $LogDir | Out-Null
$started = @{}
if (Test-Path $PidFile) {
    try {
        $saved = Get-Content $PidFile -Raw | ConvertFrom-Json
        foreach ($prop in $saved.PSObject.Properties) { $started[$prop.Name] = $prop.Value }
    } catch { $started = @{} }
}
# Python must print Korean as UTF-8 into the log file (child processes inherit this)
$env:PYTHONUTF8 = '1'

Write-Step 'Backend (FastAPI, port 8000)'
if (Test-Url $BackendUrl) {
    Write-Ok 'already running - skipped'
} elseif (Test-PortBusy 8000) {
    Write-Bad 'port 8000 is in use but not answering. Run stop (stop.cmd) first, then start again.'
    exit 1
} else {
    # same command as scripts\run-backend.ps1 (auto-reload when code changes, watch only app\)
    $p = Start-Server 'backend' $venvPython @('-m', 'uvicorn', 'app.main:app', '--reload', '--reload-dir', 'app',
        '--host', '127.0.0.1', '--port', '8000') (Join-Path $Root 'backend')
    $started['backend'] = $p.Id
    Write-Ok "starting in the background (pid $($p.Id))"
}

Write-Step 'Frontend (Vite, port 5173)'
if (Test-Url $FrontendUrl) {
    Write-Ok 'already running - skipped'
} elseif (Test-PortBusy 5173) {
    Write-Bad 'port 5173 is in use but not answering. Run stop (stop.cmd) first, then start again.'
    exit 1
} else {
    # run vite with node directly (= what 'npm run dev' does, without npm/cmd in between)
    $p = Start-Server 'frontend' $node.Source @("`"$viteJs`"") (Join-Path $Root 'frontend')
    $started['frontend'] = $p.Id
    Write-Ok "starting in the background (pid $($p.Id))"
}
$started | ConvertTo-Json | Set-Content -Encoding ascii $PidFile

# ---------------------------------------------------------------- 3) wait
Write-Step "Waiting for both servers (up to $TimeoutSec s)"
$deadline = (Get-Date).AddSeconds($TimeoutSec)
$backendOk = $false; $frontendOk = $false
while ((Get-Date) -lt $deadline -and -not ($backendOk -and $frontendOk)) {
    if (-not $backendOk -and (Test-Url $BackendUrl)) { $backendOk = $true; Write-Ok 'backend ready' }
    if (-not $frontendOk -and (Test-Url $FrontendUrl)) { $frontendOk = $true; Write-Ok 'frontend ready' }
    if (-not ($backendOk -and $frontendOk)) { Start-Sleep -Seconds 1 }
}
if (-not ($backendOk -and $frontendOk)) {
    if (-not $backendOk) { Write-Bad 'backend did not answer.'; Show-LogTail 'backend' }
    if (-not $frontendOk) { Write-Bad 'frontend did not answer.'; Show-LogTail 'frontend' }
    exit 1
}

Write-Host ''
Write-Host "VocalCut Studio is ready:  $FrontendUrl" -ForegroundColor Green
Write-Host 'The servers run in the background (no windows). To stop them: stop.cmd' -ForegroundColor Gray
if (-not $NoBrowser) { Start-Process $FrontendUrl }

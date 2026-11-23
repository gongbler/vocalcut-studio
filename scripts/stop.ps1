# Stop VocalCut Studio: stops the background servers started by start.ps1, and anything
# still listening on our ports (8000 backend, 5173 frontend).
# Running AI jobs are cancelled; unfinished jobs are marked "interrupted" at the next start.
#
# Usage (from project root):  .\scripts\stop.ps1      or double-click  stop.cmd
# NOTE: keep this file ASCII-only (see start.ps1).
$ErrorActionPreference = 'Continue'
$PidFile = Join-Path $PSScriptRoot '.pids'

function Stop-Tree($procId, $label) {
    $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if (-not $proc) { return }
    # Windows reuses process numbers: only stop it if it is still one of OUR kinds of program
    if ($proc.ProcessName -notin @('python', 'node', 'powershell')) { return }
    # /T = the whole family (uvicorn/vite + AI runner children), /F = force
    taskkill /T /F /PID $procId *> $null
    Write-Host "    stopped $label (pid $procId)" -ForegroundColor Green
}

Write-Host '==> Stopping VocalCut Studio' -ForegroundColor Cyan

# 1) the servers start.ps1 started (pid file)
if (Test-Path $PidFile) {
    try {
        $saved = Get-Content $PidFile -Raw | ConvertFrom-Json
        foreach ($prop in $saved.PSObject.Properties) { Stop-Tree ([int]$prop.Value) "$($prop.Name) server" }
    } catch { }
    Remove-Item $PidFile -ErrorAction SilentlyContinue
}

# 2) anything else still holding our ports (e.g. servers started by hand)
foreach ($port in 8000, 5173) {
    $owners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($o in $owners) {
        # uvicorn --reload runs a 'reloader' parent that would restart the worker: stop the parent too
        $parent = (Get-CimInstance Win32_Process -Filter "ProcessId=$o" -ErrorAction SilentlyContinue).ParentProcessId
        $parentName = if ($parent) { (Get-Process -Id $parent -ErrorAction SilentlyContinue).ProcessName } else { $null }
        if ($parentName -eq 'python') { Stop-Tree $parent "port $port (reloader)" }
        Stop-Tree $o "port $port"
    }
}

Start-Sleep -Milliseconds 500
$left = @(8000, 5173 | Where-Object { Get-NetTCPConnection -LocalPort $_ -State Listen -ErrorAction SilentlyContinue })
if ($left.Count -eq 0) { Write-Host 'All stopped.' -ForegroundColor Green }
else { Write-Host "Still in use: port $($left -join ', ')" -ForegroundColor Red; exit 1 }

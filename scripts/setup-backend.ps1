# Create the backend virtual environment (.venv) and install packages.
# Usage (from project root): .\scripts\setup-backend.ps1
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..\backend')

if (-not (Test-Path '.venv')) {
    Write-Host '[1/2] Creating virtual environment (.venv)...'
    python -m venv .venv
}

Write-Host '[2/2] Installing packages...'
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt

Write-Host 'Done! Start the server with: .\scripts\run-backend.ps1'

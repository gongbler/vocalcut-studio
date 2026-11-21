# Start the FastAPI dev server (auto-restarts when code is saved).
# Usage (from project root): .\scripts\run-backend.ps1
Set-Location (Join-Path $PSScriptRoot '..\backend')
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

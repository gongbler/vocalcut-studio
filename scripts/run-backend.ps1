# Start the FastAPI dev server (auto-restarts when code is saved).
# Usage (from project root): .\scripts\run-backend.ps1
#
# --reload-dir app : watch ONLY our source folder. Without it, uvicorn also watches .venv,
#                    so every `pip install` restarts the server and interrupts running jobs.
Set-Location (Join-Path $PSScriptRoot '..\backend')
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --reload-dir app --host 127.0.0.1 --port 8000

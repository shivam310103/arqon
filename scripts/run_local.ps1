# Run ARQON locally on Windows. From the project folder:  .\scripts\run_local.ps1
$ErrorActionPreference = "Stop"
if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -q -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env; Write-Host "Created .env - add your GEMINI_API_KEY, then run again." ; exit }
Write-Host "Open http://localhost:8080"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8080 --reload

param(
    [switch]$SkipInstall
)
$root = Split-Path -Parent $PSScriptRoot
if (-not $SkipInstall) {
  Push-Location "$root\backend"
  python -m pip install -e ".[dev]"
  Pop-Location
  Push-Location "$root\frontend"
  npm install
  Pop-Location
}
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\backend'; python -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
Start-Sleep -Seconds 2
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\backend'; python -m app.worker"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\frontend'; npm run dev"
Write-Output "API http://127.0.0.1:8000/api/health"
Write-Output "UI  http://127.0.0.1:5173"

@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if defined PYTHON (
  set "PY=%PYTHON%"
) else if exist "D:\miniforge\python.exe" (
  set "PY=D:\miniforge\python.exe"
) else (
  set "PY=python"
)

if not exist "frontend\dist\index.html" (
  echo Building the UI once. This needs Node.js.
  pushd frontend
  call npm run build
  if errorlevel 1 (
    echo UI build failed. Install Node 20+ and run: cd frontend ^&^& npm install ^&^& npm run build
    popd
    pause
    exit /b 1
  )
  popd
)

echo Starting GEOScout. Keep this window open. Close it to stop.
echo Browser should open http://127.0.0.1:8000/
pushd backend
"%PY%" -m app.launcher
set "ERR=%ERRORLEVEL%"
popd
if not "%ERR%"=="0" pause
exit /b %ERR%

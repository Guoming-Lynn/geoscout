@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PY="
if defined PYTHON set "PY=%PYTHON%"
if not defined PY (
  py -3 -c "import sys; raise SystemExit(0 if sys.version_info>=(3,11) else 1)" >nul 2>&1
  if not errorlevel 1 for /f "delims=" %%I in ('py -3 -c "import sys; print(sys.executable)"') do set "PY=%%I"
)
if not defined PY (
  python -c "import sys; raise SystemExit(0 if sys.version_info>=(3,11) else 1)" >nul 2>&1
  if not errorlevel 1 for /f "delims=" %%I in ('python -c "import sys; print(sys.executable)"') do set "PY=%%I"
)
if not defined PY if exist "%LocalAppData%\miniforge3\python.exe" set "PY=%LocalAppData%\miniforge3\python.exe"
if not defined PY if exist "D:\miniforge\python.exe" set "PY=D:\miniforge\python.exe"
if not defined PY (
  echo Python 3.11+ was not found. Install Python, or set PYTHON to your interpreter.
  pause
  exit /b 1
)

if not exist "frontend\dist\index.html" (
  echo Building the UI once. This needs Node.js.
  pushd frontend
  if not exist "node_modules\" (
    call npm install
    if errorlevel 1 (
      echo npm install failed. Install Node 20+ first.
      popd
      pause
      exit /b 1
    )
  )
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
echo Using: %PY%
echo Browser should open http://127.0.0.1:8000/
pushd backend
"%PY%" -m app.launcher
set "ERR=%ERRORLEVEL%"
popd
if not "%ERR%"=="0" pause
exit /b %ERR%

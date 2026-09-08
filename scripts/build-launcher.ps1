param(
    [switch]$SkipUiBuild
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = if ($env:PYTHON) {
    $env:PYTHON
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    "python"
} elseif (Test-Path "D:\miniforge\python.exe") {
    "D:\miniforge\python.exe"
} else {
    "python"
}

if (-not $SkipUiBuild) {
    Push-Location "$root\frontend"
    npm run build
    Pop-Location
}

$index = Join-Path $root "frontend\dist\index.html"
if (-not (Test-Path $index)) {
    throw "frontend/dist/index.html missing. Run npm run build in frontend/."
}

& $python -m pip install "pyinstaller>=6.11"
Push-Location $root
& $python -m PyInstaller --noconfirm --clean --distpath "$root\dist" --workpath "$root\build\pyinstaller" "$root\packaging\geoscout.spec"
Pop-Location

$exe = Join-Path $root "dist\GEOScout\GEOScout.exe"
if (-not (Test-Path $exe)) {
    throw "GEOScout.exe was not produced."
}
Write-Output "Built $exe"
Write-Output "Double-click GEOScout.exe. Keep the console open. UI: http://127.0.0.1:8000/"
Write-Output "Data folder is created next to the exe as data\."

# -*- mode: python ; coding: utf-8 -*-
"""One-folder GEOScout launcher. Run via scripts/build-launcher.ps1."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPEC).resolve().parent.parent
BACKEND = ROOT / "backend"
WEB = ROOT / "frontend" / "dist"
PROMPTS = BACKEND / "app" / "prompts"

if not (WEB / "index.html").is_file():
    raise SystemExit("frontend/dist is missing. Run: cd frontend && npm run build")

datas = [
    (str(PROMPTS), "app/prompts"),
    (str(WEB), "web"),
]
binaries = []
hiddenimports = [
    "app.main",
    "app.worker",
    "app.web",
    "app.paths",
    "app.launcher",
    "aiosqlite",
    "greenlet",
    "openpyxl",
    "orjson",
    "multipart",
    "python_multipart",
    "pydantic_settings",
    "sqlalchemy.dialects.sqlite",
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
]
hiddenimports += collect_submodules("app")

for pkg in ("uvicorn", "fastapi", "starlette", "pydantic", "httpx", "anyio"):
    collected_datas, collected_binaries, collected_hidden = collect_all(pkg)
    datas += collected_datas
    binaries += collected_binaries
    hiddenimports += collected_hidden

a = Analysis(
    [str(BACKEND / "app" / "launcher.py")],
    pathex=[str(BACKEND)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "numpy",
        "pandas",
        "scipy",
        "pytest",
        "IPython",
        "notebook",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GEOScout",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="GEOScout",
)

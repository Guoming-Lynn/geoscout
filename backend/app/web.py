from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def mount_web(app: FastAPI, web_root: Path) -> None:
    root = web_root.resolve()
    index = root / "index.html"
    if not index.is_file():
        raise FileNotFoundError(f"missing {index}")
    assets = root / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="web-assets")

    def _safe_file(full_path: str) -> Path | None:
        target = (root / full_path).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return None
        return target if target.is_file() else None

    @app.get("/", include_in_schema=False)
    async def web_index() -> FileResponse:
        return FileResponse(index)

    @app.get("/{full_path:path}", include_in_schema=False)
    async def web_spa(full_path: str) -> FileResponse:
        if full_path.startswith(("api/", "internal/", "assets/")):
            raise HTTPException(status_code=404)
        found = _safe_file(full_path)
        if found is not None:
            return FileResponse(found)
        return FileResponse(index)

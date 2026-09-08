from pathlib import Path

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest

from app.paths import web_dir
from app.web import mount_web


def test_web_dir_missing_is_none(tmp_path, monkeypatch):
    monkeypatch.setattr("app.paths.exe_dir", lambda: tmp_path)
    monkeypatch.setattr("app.paths.bundle_dir", lambda: tmp_path)
    assert web_dir() is None


def test_web_dir_finds_index(tmp_path, monkeypatch):
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "index.html").write_text("<html>ui</html>", encoding="utf-8")
    monkeypatch.setattr("app.paths.frozen", lambda: True)
    monkeypatch.setattr("app.paths.bundle_dir", lambda: tmp_path)
    monkeypatch.setattr("app.paths.exe_dir", lambda: tmp_path)
    found = web_dir()
    assert found is not None
    assert found.name == "web"


@pytest.mark.asyncio
async def test_mount_web_serves_spa_and_leaves_api(tmp_path):
    web = tmp_path / "dist"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<html>geoscout-ui</html>", encoding="utf-8")
    (web / "assets" / "app.js").write_text("ok", encoding="utf-8")
    app = FastAPI()

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    mount_web(app, web)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
        home = await client.get("/")
        assert home.status_code == 200
        assert b"geoscout-ui" in home.content
        spa = await client.get("/workbench")
        assert spa.status_code == 200
        assert b"geoscout-ui" in spa.content
        asset = await client.get("/assets/app.js")
        assert asset.status_code == 200
        assert asset.text == "ok"
        api = await client.get("/api/health")
        assert api.status_code == 200
        assert api.json() == {"ok": True}
        traversal = await client.get("/assets/../../index.html")
        assert traversal.status_code in {200, 404}
        if traversal.status_code == 200:
            # Starlette may normalize; still must not escape the web root.
            assert b"geoscout-ui" in traversal.content


def test_launcher_defaults_bind_localhost():
    from app.launcher import launcher_defaults

    defaults = launcher_defaults(Path("/tmp/geoscout-data"))
    assert defaults["GEOSCOUT_HOST"] == "127.0.0.1"
    assert defaults["GEOSCOUT_EMBED_WORKER"] == "true"
    assert defaults["GEOSCOUT_SERVE_WEB"] == "true"
    assert defaults["GEOSCOUT_API_URL"].startswith("http://127.0.0.1")

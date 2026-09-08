import pytest
from httpx import ASGITransport, AsyncClient

from app.db.models import Project
from app.db.session import SessionLocal, init_db
from app.main import app
from sqlalchemy import func, select


@pytest.mark.asyncio
async def test_clear_workspace_removes_projects():
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
        created = await client.post("/api/projects", json={"original_request": "clear-me", "name": "pipe"})
        assert created.status_code == 200, created.text
        cleared = await client.post("/api/workspace/clear")
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["ok"] is True
        listed = await client.get("/api/projects")
        assert listed.status_code == 200
        assert listed.json() == []
    async with SessionLocal() as session:
        count = await session.scalar(select(func.count()).select_from(Project))
        assert count == 0

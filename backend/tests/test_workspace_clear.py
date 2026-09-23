import pytest
from httpx import ASGITransport, AsyncClient

from app.db.models import Project, Run
from app.db.session import SessionLocal, init_db
from app.evidence.store import new_id
from app.main import app
from sqlalchemy import func, select, update


@pytest.mark.asyncio
async def test_clear_workspace_removes_projects():
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
        created = await client.post("/api/projects", json={"original_request": "clear-me", "name": "pipe"})
        assert created.status_code == 200, created.text
    async with SessionLocal() as session:
        await session.execute(update(Run).values(status="cancelled"))
        await session.commit()
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
        cleared = await client.post("/api/workspace/clear")
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["ok"] is True
        listed = await client.get("/api/projects")
        assert listed.status_code == 200
        assert listed.json() == []
    async with SessionLocal() as session:
        count = await session.scalar(select(func.count()).select_from(Project))
        assert count == 0


@pytest.mark.asyncio
async def test_clear_workspace_refuses_active_run():
    await init_db()
    async with SessionLocal() as session:
        project = Project(id=new_id(), name="busy", original_request="x")
        session.add(project)
        await session.flush()
        session.add(Run(id=new_id(), project_id=project.id, status="running"))
        await session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1:8000") as client:
        refused = await client.post("/api/workspace/clear")
        assert refused.status_code == 409
        listed = await client.get("/api/projects")
        assert any(item["name"] == "busy" for item in listed.json())

import asyncio
from types import SimpleNamespace

import pytest

from app.api import sse_events
from app.db.models import Project, Run
from app.db.session import SessionLocal, engine, init_db
from app.evidence.store import new_id
from app.pipeline.repo import add_event


@pytest.mark.asyncio
async def test_event_stream_releases_connection_and_observes_completion():
    await init_db()
    async with SessionLocal() as db:
        p = Project(id=new_id(), name="sse", original_request="test")
        db.add(p)
        await db.flush()
        run = Run(id=new_id(), project_id=p.id, status="running")
        db.add(run)
        await db.flush()
        await add_event(db, run.id, "started")
        await db.commit()
        rid = run.id

    async def connected():
        return False

    request = SimpleNamespace(headers={}, query_params={}, is_disconnected=connected)
    response = await sse_events(rid, request)
    stream = response.body_iterator
    try:
        first = await anext(stream)
        assert "started" in first
        assert engine.pool.checkedout() == 0
        async with SessionLocal() as db:
            run = await db.get(Run, rid)
            run.status = "completed"
            await db.commit()
        done = await asyncio.wait_for(anext(stream), timeout=3)
        assert '"status": "completed"' in done
        assert engine.pool.checkedout() == 0
    finally:
        await stream.aclose()

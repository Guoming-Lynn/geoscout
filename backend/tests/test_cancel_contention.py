import sqlite3

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.api import cancel_run
from app.db.models import Event, Project, Run
from app.db.session import SessionLocal, init_db
from app.evidence.store import new_id


async def make_run():
    await init_db()
    async with SessionLocal() as db:
        project = Project(id=new_id(), name="cancel", original_request="test")
        db.add(project)
        await db.flush()
        run = Run(id=new_id(), project_id=project.id, status="running")
        db.add(run)
        await db.commit()
        return run.id


@pytest.mark.asyncio
async def test_cancel_retries_failed_transaction_without_duplicate_events(monkeypatch):
    rid = await make_run()
    async with SessionLocal() as db:
        commit = db.commit
        attempts = 0

        async def intermittent_commit():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise OperationalError("UPDATE runs", {}, sqlite3.OperationalError("database is locked"))
            await commit()

        monkeypatch.setattr(db, "commit", intermittent_commit)
        result = await cancel_run(rid, db)
        assert result["id"] == rid
        await cancel_run(rid, db)
    async with SessionLocal() as db:
        assert (await db.get(Run, rid)).cancel_requested
        events = (await db.execute(select(Event).where(Event.run_id == rid))).scalars().all()
        assert len(events) == 1


@pytest.mark.asyncio
async def test_cancel_persistent_lock_returns_retryable_failure(monkeypatch):
    rid = await make_run()
    async with SessionLocal() as db:
        async def locked_commit():
            raise OperationalError("UPDATE runs", {}, sqlite3.OperationalError("database is locked"))

        monkeypatch.setattr(db, "commit", locked_commit)
        with pytest.raises(HTTPException) as caught:
            await cancel_run(rid, db)
        assert caught.value.status_code == 503
        assert caught.value.headers["Retry-After"] == "2"
    async with SessionLocal() as db:
        assert not (await db.get(Run, rid)).cancel_requested
        assert not (await db.execute(select(Event).where(Event.run_id == rid))).scalars().all()

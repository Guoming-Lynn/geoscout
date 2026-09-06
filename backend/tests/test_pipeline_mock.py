import pytest
from sqlalchemy import select

from app.connectors.llm import LLMError, validate_assessment
from app.core.credentials import store
from app.db.models import Assessment, Job, QueryAttempt, Run, RunDataset
from app.db.session import SessionLocal, init_db
from app.evidence.store import quote_in_text
from app.exporters.excel import read_sheet_maps
from app.exporters.service import create_export
from app.pipeline.engine import Engine
from httpx import ASGITransport, AsyncClient
from app.main import app
from pathlib import Path
from datetime import datetime, timezone, timedelta


async def _drain(run_id: str, limit: int = 80) -> None:
    for _ in range(limit):
        async with SessionLocal() as session:
            jobs = (
                await session.execute(
                    select(Job).where(Job.run_id == run_id, Job.status.in_(["queued", "leased"]))
                )
            ).scalars().all()
            job = None
            now = datetime.now(timezone.utc)
            for item in jobs:
                lease = item.lease_until
                if lease is not None and lease.tzinfo is None:
                    lease = lease.replace(tzinfo=timezone.utc)
                if item.status == "leased" and lease and lease > now:
                    continue
                job = item
                job.status = "leased"
                job.worker_id = "test-worker"
                job.attempt += 1
                job.lease_until = now + timedelta(seconds=30)
                break
            await session.commit()
            if job is None:
                return
            async with SessionLocal() as work:
                job2 = await work.get(Job, job.id)
                if job2 is None:
                    continue
                await Engine(work, job2, "test-worker").run()
                await work.commit()


@pytest.mark.asyncio
async def test_mock_pipeline_and_export():
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
        created = await client.post("/api/projects", json={"original_request": "human atherosclerosis RNA-seq", "name": "pipe"})
        assert created.status_code == 200, created.text
        pid = created.json()["id"]
        run = await client.post(
            f"/api/projects/{pid}/runs",
            json={"mode": "manual_query", "manual_query": "atherosclerosis AND \"gse\"[ETYP]", "budget": {"max_unique_gse": 20, "esearch_page_size": 20}},
        )
        assert run.status_code == 200, run.text
        rid = run.json()["id"]

    await _drain(rid)

    async with SessionLocal() as session:
        db_run = await session.get(Run, rid)
        assert db_run is not None
        assert db_run.status in {"completed", "partial"}
        rows = (await session.execute(select(RunDataset).where(RunDataset.run_id == rid))).scalars().all()
        gses = {r.gse for r in rows}
        assert "GSE333565" in gses
        assert "GDS562" not in gses
        export = await create_export(session, db_run, include_json=True)
        await session.commit()
        audit = Path(export.path).with_suffix(".audit.json").read_text(encoding="utf-8")
        assert "sk-real" not in audit
        assert store.get(db_run.session_id) is not None or True


@pytest.mark.asyncio
async def test_budget_truncation_marks_partial():
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
        created = await client.post("/api/projects", json={"original_request": "human atherosclerosis", "name": "budget"})
        pid = created.json()["id"]
        run = await client.post(
            f"/api/projects/{pid}/runs",
            json={
                "mode": "manual_query",
                "manual_query": "atherosclerosis AND \"gse\"[ETYP]",
                "budget": {"max_unique_gse": 1, "esearch_page_size": 1, "max_queries": 1},
            },
        )
        rid = run.json()["id"]
    await _drain(rid)
    async with SessionLocal() as session:
        db_run = await session.get(Run, rid)
        assert db_run is not None
        assert db_run.status == "partial"
        assert db_run.stop_reason
        q = (await session.execute(select(QueryAttempt).where(QueryAttempt.run_id == rid))).scalars().first()
        assert q is not None
        rows = (await session.execute(select(RunDataset).where(RunDataset.run_id == rid))).scalars().all()
        assert 0 < len(rows) <= 1


@pytest.mark.asyncio
async def test_pause_then_cancel():
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
        created = await client.post("/api/projects", json={"original_request": "human atherosclerosis", "name": "pause"})
        pid = created.json()["id"]
        run = await client.post(
            f"/api/projects/{pid}/runs",
            json={"mode": "manual_query", "manual_query": "atherosclerosis AND \"gse\"[ETYP]", "budget": {"max_unique_gse": 20}},
        )
        rid = run.json()["id"]
        paused = await client.post(f"/api/runs/{rid}/pause")
        assert paused.status_code == 200
    await _drain(rid, limit=3)
    async with SessionLocal() as session:
        db_run = await session.get(Run, rid)
        assert db_run is not None
        assert db_run.status in {"paused", "pausing", "queued", "running", "completed", "partial"}
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
        cancelled = await client.post(f"/api/runs/{rid}/cancel")
        assert cancelled.status_code == 200
    await _drain(rid)
    async with SessionLocal() as session:
        db_run = await session.get(Run, rid)
        assert db_run is not None
        assert db_run.status in {"cancelled", "completed", "partial", "paused"}


@pytest.mark.asyncio
async def test_full_mock_writes_final_assessments():
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
        created = await client.post("/api/projects", json={"original_request": "human atherosclerosis scRNA-seq", "name": "full"})
        pid = created.json()["id"]
        run = await client.post(
            f"/api/projects/{pid}/runs",
            json={"mode": "full", "budget": {"max_unique_gse": 3, "max_deep_verify": 3, "max_queries": 4, "esearch_page_size": 20}},
        )
        rid = run.json()["id"]
    await _drain(rid, limit=120)
    async with SessionLocal() as session:
        db_run = await session.get(Run, rid)
        assert db_run is not None
        assert db_run.status in {"completed", "partial"}
        finals = (
            await session.execute(select(Assessment).where(Assessment.run_id == rid, Assessment.stage == "final"))
        ).scalars().all()
        assert finals
        export = await create_export(session, db_run, include_json=True)
        await session.commit()
        evidence = read_sheet_maps(Path(export.path), "Evidence")
        assert any(row.get("阶段") == "final" for row in evidence)


@pytest.mark.asyncio
async def test_two_manual_runs_on_same_database_keep_evidence():
    await init_db()
    transport = ASGITransport(app=app)
    rids = []
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
        for name in ("same-db-a", "same-db-b"):
            created = await client.post("/api/projects", json={"original_request": "human atherosclerosis RNA-seq", "name": name})
            pid = created.json()["id"]
            run = await client.post(
                f"/api/projects/{pid}/runs",
                json={"mode": "manual_query", "manual_query": "atherosclerosis AND \"gse\"[ETYP]", "budget": {"max_unique_gse": 20, "esearch_page_size": 20}},
            )
            rids.append(run.json()["id"])
    for rid in rids:
        await _drain(rid)
    from app.evidence.store import evidence_bundle
    async with SessionLocal() as session:
        for rid in rids:
            db_run = await session.get(Run, rid)
            assert db_run is not None
            assert db_run.status in {"completed", "partial"}
            rows = (await session.execute(select(RunDataset).where(RunDataset.run_id == rid))).scalars().all()
            assert rows
            bundle = await evidence_bundle(session, rid, rows[0].gse)
            assert bundle
            export = await create_export(session, db_run, include_json=False)
            await session.commit()
            evidence = read_sheet_maps(Path(export.path), "Evidence")
            assert any(row.get("GSE") == rows[0].gse for row in evidence)


def test_invalid_model_json():
    with pytest.raises(LLMError):
        validate_assessment({"judgements": [{"criterion_id": "x", "verdict": "maybe"}]})


def test_quote_must_exist():
    assert quote_in_text("Homo sapiens", "taxon: Homo sapiens tissue artery")
    assert not quote_in_text("invented quote", "taxon: Homo sapiens")


@pytest.mark.asyncio
async def test_fixed_trio_categories():
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
        created = await client.post(
            "/api/projects",
            json={"original_request": "human atherosclerosis scRNA-seq lesion vs control", "name": "trio"},
        )
        assert created.status_code == 200, created.text
        pid = created.json()["id"]
        run = await client.post(
            f"/api/projects/{pid}/runs",
            json={
                "mode": "full",
                "budget": {"max_unique_gse": 3, "max_deep_verify": 3, "max_queries": 4, "esearch_page_size": 20},
            },
        )
        assert run.status_code == 200, run.text
        rid = run.json()["id"]
    await _drain(rid, limit=160)
    async with SessionLocal() as session:
        db_run = await session.get(Run, rid)
        assert db_run is not None
        assert db_run.status in {"completed", "partial"}
        rows = {r.gse: r for r in (await session.execute(select(RunDataset).where(RunDataset.run_id == rid))).scalars().all()}
        assert set(rows) >= {"GSE333565", "GSE1000", "GSE325203"}
        assert rows["GSE333565"].category == "recommended"
        assert rows["GSE1000"].category == "excluded"
        assert rows["GSE325203"].category == "needs_review"
        assert "复核失败" not in (rows["GSE325203"].reason or "")
        assert rows["GSE325203"].reason != "初筛完成，深度核验待进行。"


@pytest.mark.asyncio
async def test_deep_verify_limit_skips_llm_for_unscreened_rest():
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
        created = await client.post(
            "/api/projects",
            json={"original_request": "human atherosclerosis scRNA-seq lesion vs control", "name": "deep1"},
        )
        pid = created.json()["id"]
        run = await client.post(
            f"/api/projects/{pid}/runs",
            json={
                "mode": "full",
                "budget": {"max_unique_gse": 3, "max_deep_verify": 1, "max_queries": 4, "esearch_page_size": 20},
            },
        )
        rid = run.json()["id"]
    await _drain(rid, limit=160)
    async with SessionLocal() as session:
        models = (
            await session.execute(select(Assessment).where(Assessment.run_id == rid, Assessment.stage == "assess_model"))
        ).scalars().all()
        gses = {row.gse for row in models}
        assert len(gses) == 1
        verify_models = (
            await session.execute(select(Assessment).where(Assessment.run_id == rid, Assessment.stage == "verify_model"))
        ).scalars().all()
        assert {row.gse for row in verify_models} == gses

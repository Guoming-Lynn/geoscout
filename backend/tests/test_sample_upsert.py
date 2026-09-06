import pytest
from sqlalchemy import func, select

from app.db.models import Job, Project, Run, RunDataset, Sample
from app.db.session import SessionLocal, init_db
from app.evidence.store import new_id
from app.pipeline.engine import Engine
from app.pipeline.repo import dump, upsert_dataset, upsert_run_dataset, upsert_sample
from app.schemas.spec import ResearchSpec


async def _make_run(gse: str = "GSE333565") -> tuple[str, str]:
    await init_db()
    async with SessionLocal() as session:
        if await session.get(Project, "p-upsert") is None:
            session.add(Project(id="p-upsert", name="upsert", original_request="human scRNA-seq"))
        await upsert_dataset(
            session,
            {
                "accession": gse,
                "uid": "200333565",
                "title": "fixture",
                "summary": "single-cell",
                "taxon": "Homo sapiens",
                "gdstype": "Expression profiling by high throughput sequencing",
            },
        )
        run = Run(
            id=new_id(),
            project_id="p-upsert",
            session_id="s-upsert",
            mode="full",
            spec_snapshot=dump(ResearchSpec(original_request="human scRNA-seq", organisms=["Homo sapiens"]).model_dump()),
            budget_json=dump({"max_deep_verify": 5, "max_unique_gse": 10}),
            status="running",
            stage="fetching",
            config_summary=dump({"demo": False}),
        )
        session.add(run)
        await upsert_run_dataset(session, run.id, gse, "term")
        await session.commit()
        return run.id, gse


async def _deep_once(run_id: str) -> None:
    async with SessionLocal() as session:
        job = Job(id=new_id(), run_id=run_id, step="deep_fetch", status="leased", payload_json=dump({"index": 0}))
        session.add(job)
        await session.commit()
        job2 = await session.get(Job, job.id)
        run = await session.get(Run, run_id)
        await Engine(session, job2, "test-worker").step_deep_fetch(run)
        await session.commit()


@pytest.mark.asyncio
async def test_sample_upsert_does_not_duplicate_gsm():
    payload = {
        "gsm": "GSM1",
        "title": "first",
        "organism": "Homo sapiens",
        "source_name": "blood",
        "characteristics": [],
        "library_strategy": "RNA-Seq",
        "donor_key": "donor_id=D1",
    }
    await init_db()
    async with SessionLocal() as session:
        await upsert_dataset(session, {"accession": "GSE1", "title": "t", "summary": "", "taxon": "Homo sapiens", "gdstype": ""})
        await upsert_sample(session, "GSE1", payload, truncated=False)
        payload["title"] = "updated"
        await upsert_sample(session, "GSE1", payload, truncated=False)
        await session.commit()
        n = (await session.execute(select(func.count()).select_from(Sample).where(Sample.gse == "GSE1", Sample.gsm == "GSM1"))).scalar()
        row = (await session.execute(select(Sample).where(Sample.gse == "GSE1", Sample.gsm == "GSM1"))).scalar_one()
    assert n == 1
    assert row.title == "updated"


@pytest.mark.asyncio
async def test_deep_fetch_twice_same_gse_is_idempotent():
    run_id, gse = await _make_run()
    await _deep_once(run_id)
    await _deep_once(run_id)
    async with SessionLocal() as session:
        n = (await session.execute(select(func.count()).select_from(Sample).where(Sample.gse == gse))).scalar()
        gsms = (await session.execute(select(Sample.gsm).where(Sample.gse == gse))).scalars().all()
        rd = (
            await session.execute(select(RunDataset).where(RunDataset.run_id == run_id, RunDataset.gse == gse))
        ).scalar_one()
    assert n == len(set(gsms))
    assert n > 0
    assert rd.verification_status in {"soft_loaded", "soft_incomplete"}


@pytest.mark.asyncio
async def test_two_runs_share_samples_without_breaking_either():
    run_a, gse = await _make_run("GSE333565")
    await _deep_once(run_a)
    async with SessionLocal() as session:
        run_b = Run(
            id=new_id(),
            project_id="p-upsert",
            session_id="s-upsert-b",
            mode="full",
            spec_snapshot=dump(ResearchSpec(original_request="human scRNA-seq", organisms=["Homo sapiens"]).model_dump()),
            budget_json=dump({"max_deep_verify": 5}),
            status="running",
            stage="fetching",
            config_summary=dump({"demo": False}),
        )
        session.add(run_b)
        await upsert_run_dataset(session, run_b.id, gse, "term2")
        await session.commit()
        rid_b = run_b.id
    await _deep_once(rid_b)
    async with SessionLocal() as session:
        n = (await session.execute(select(func.count()).select_from(Sample).where(Sample.gse == gse))).scalar()
        gsms = (await session.execute(select(Sample.gsm).where(Sample.gse == gse))).scalars().all()
        a = (await session.execute(select(RunDataset).where(RunDataset.run_id == run_a))).scalar_one()
        b = (await session.execute(select(RunDataset).where(RunDataset.run_id == rid_b))).scalar_one()
    assert n == len(set(gsms))
    assert a.gse == b.gse == gse
    assert a.gsm_count == b.gsm_count

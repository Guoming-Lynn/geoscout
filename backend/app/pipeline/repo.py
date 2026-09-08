from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Assessment,
    Dataset,
    Event,
    Evidence,
    Export,
    Job,
    Override,
    Project,
    QueryAttempt,
    Run,
    RunDataset,
    RunEvidence,
    Sample,
    utcnow,
)
from app.evidence.store import new_id
from app.pipeline.donors import infer_group_label


def dump(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


def load(text: str | None, default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


async def add_event(session: AsyncSession, run_id: str, message: str, *, level: str = "info", payload: dict | None = None) -> None:
    session.add(Event(run_id=run_id, level=level, message=message, payload_json=dump(payload or {})))


async def bump_counters(session: AsyncSession, run: Run, **delta: int) -> dict[str, Any]:
    counters = load(run.counters_json, {})
    for key, value in delta.items():
        counters[key] = int(counters.get(key) or 0) + int(value)
    run.counters_json = dump(counters)
    return counters


async def enqueue_job(session: AsyncSession, run_id: str, step: str, payload: dict | None = None) -> Job | None:
    run = await session.get(Run, run_id)
    if run is not None and run.status in {"completed", "partial", "failed", "cancelled"}:
        return None
    job = Job(
        id=new_id(),
        run_id=run_id,
        step=step,
        status="queued",
        payload_json=dump(payload or {}),
    )
    session.add(job)
    return job


async def claim_job(session: AsyncSession, worker_id: str, lease_s: int) -> Job | None:
    now = utcnow()
    # SQLite has limited SKIP LOCKED; filter expired leases in Python.
    jobs = (
        await session.execute(select(Job).where(Job.status.in_(["queued", "leased"])).order_by(Job.created_at.asc()))
    ).scalars().all()
    run_ids = {job.run_id for job in jobs}
    runs = {}
    if run_ids:
        runs = {
            row.id: row
            for row in (await session.execute(select(Run).where(Run.id.in_(run_ids)))).scalars().all()
        }
    for job in jobs:
        lease_until = job.lease_until
        if lease_until is not None and lease_until.tzinfo is None:
            lease_until = lease_until.replace(tzinfo=timezone.utc)
        if job.status == "leased" and lease_until and lease_until > now:
            continue
        run = runs.get(job.run_id)
        if run is None:
            continue
        if run.status == "waiting_for_credentials":
            continue
        if run.status in {"completed", "partial", "failed", "cancelled"}:
            job.status = "cancelled"
            job.last_error = "任务已结束"
            job.updated_at = now
            continue
        job.status = "leased"
        job.worker_id = worker_id
        job.attempt += 1
        job.lease_until = now + timedelta(seconds=lease_s)
        job.updated_at = now
        return job
    return None


async def heartbeat(session: AsyncSession, job: Job, lease_s: int) -> None:
    job.lease_until = utcnow() + timedelta(seconds=lease_s)
    job.updated_at = utcnow()


async def upsert_dataset(session: AsyncSession, summary: dict[str, Any]) -> Dataset:
    gse = summary["accession"].upper()
    row = await session.get(Dataset, gse)
    payload = dump(summary)
    if row is None:
        row = Dataset(gse=gse)
        session.add(row)
    row.uid = str(summary.get("uid") or "")
    row.title = summary.get("title") or ""
    row.summary = summary.get("summary") or ""
    row.taxon = summary.get("taxon") or ""
    row.gdstype = summary.get("gdstype") or ""
    row.gpl = str(summary.get("gpl") or "")
    row.n_samples = summary.get("n_samples")
    row.pdat = str(summary.get("pdat") or "")
    row.pubmed_ids = dump(summary.get("pubmedids") or [])
    row.suppfile = summary.get("suppfile") or ""
    row.ftplink = summary.get("ftplink") or ""
    row.bioproject = str(summary.get("bioproject") or "")
    row.summary_json = payload
    row.fetched_at = utcnow()
    return row


async def upsert_run_dataset(session: AsyncSession, run_id: str, gse: str, query_term: str) -> tuple[RunDataset, bool]:
    existing = (
        await session.execute(select(RunDataset).where(RunDataset.run_id == run_id, RunDataset.gse == gse))
    ).scalar_one_or_none()
    if existing:
        hits = load(existing.hit_queries, [])
        if query_term not in hits:
            hits.append(query_term)
            existing.hit_queries = dump(hits)
        return existing, False
    row = RunDataset(id=new_id(), run_id=run_id, gse=gse, hit_queries=dump([query_term]))
    session.add(row)
    return row, True


async def upsert_sample(
    session: AsyncSession,
    gse: str,
    sample: dict[str, Any],
    *,
    truncated: bool = False,
) -> Sample:
    gsm = str(sample.get("gsm") or "").strip()
    existing = (
        await session.execute(select(Sample).where(Sample.gse == gse, Sample.gsm == gsm))
    ).scalar_one_or_none()
    if existing is None:
        existing = Sample(id=new_id(), gse=gse, gsm=gsm)
        session.add(existing)
    existing.title = sample.get("title") or ""
    existing.organism = sample.get("organism") or ""
    existing.source_name = sample.get("source_name") or ""
    existing.characteristics_json = dump(sample.get("characteristics") or [])
    existing.library_strategy = sample.get("library_strategy") or ""
    existing.donor_key = sample.get("donor_key")
    existing.group_label = infer_group_label(sample)
    existing.attrs_json = dump(sample)
    existing.coverage_incomplete = truncated
    return existing


async def clear_workspace(session: AsyncSession) -> dict[str, int]:
    """Delete projects, runs, and export files. Keep GEO dataset cache."""
    export_paths = (await session.execute(select(Export.path))).scalars().all()
    deleted: dict[str, int] = {}
    for model in (
        Job,
        Event,
        Override,
        Assessment,
        RunEvidence,
        Evidence,
        RunDataset,
        QueryAttempt,
        Export,
        Run,
        Project,
    ):
        result = await session.execute(delete(model))
        deleted[model.__tablename__] = int(result.rowcount or 0)
    for raw in export_paths:
        path = Path(str(raw))
        try:
            path.unlink(missing_ok=True)
            audit = path.with_suffix(".audit.json")
            audit.unlink(missing_ok=True)
        except OSError:
            continue
    return deleted

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.urls import accession_page
from app.db.models import Evidence, RunEvidence


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def evidence_id_for(gse: str, field_path: str, text: str) -> str:
    raw = f"{gse}|{field_path}|{content_hash(text)}"
    return "ev_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


async def add_evidence(
    session: AsyncSession,
    *,
    run_id: str,
    gse: str,
    source_url: str,
    field_path: str,
    text: str,
) -> Evidence:
    eid = evidence_id_for(gse, field_path, text)
    existing = await session.get(Evidence, eid)
    now = datetime.now(timezone.utc)
    if existing is None:
        existing = Evidence(
            id=eid,
            run_id=run_id,
            gse=gse,
            source_url=source_url,
            field_path=field_path,
            text=text[:20000],
            content_hash=content_hash(text),
            fetched_at=now,
        )
        session.add(existing)
        await session.flush()
    link = (
        await session.execute(
            select(RunEvidence).where(RunEvidence.run_id == run_id, RunEvidence.evidence_id == eid)
        )
    ).scalar_one_or_none()
    if link is None:
        session.add(
            RunEvidence(
                id=new_id(),
                run_id=run_id,
                evidence_id=eid,
                source_url=source_url,
                field_path=field_path,
                fetched_at=now,
                rebuilt=False,
            )
        )
    return existing


async def evidence_bundle(session: AsyncSession, run_id: str, gse: str | None = None) -> list[dict[str, Any]]:
    stmt = (
        select(RunEvidence, Evidence)
        .join(Evidence, Evidence.id == RunEvidence.evidence_id)
        .where(RunEvidence.run_id == run_id)
    )
    if gse:
        stmt = stmt.where(Evidence.gse == gse)
    rows = (await session.execute(stmt)).all()
    if rows:
        return [
            {
                "evidence_id": ev.id,
                "source_url": link.source_url or ev.source_url,
                "field_path": link.field_path or ev.field_path,
                "text": ev.text,
            }
            for link, ev in rows
        ]
    fallback = select(Evidence).where(Evidence.run_id == run_id)
    if gse:
        fallback = fallback.where(Evidence.gse == gse)
    old = (await session.execute(fallback)).scalars().all()
    return [
        {
            "evidence_id": row.id,
            "source_url": row.source_url,
            "field_path": row.field_path,
            "text": row.text,
        }
        for row in old
    ]


def quote_in_text(quote: str, text: str) -> bool:
    if not quote.strip():
        return False
    norm_q = " ".join(quote.split())
    norm_t = " ".join(text.split())
    return norm_q in norm_t


def write_snapshot(run_id: str, name: str, payload: Any) -> Path:
    folder = settings.snapshot_dir / run_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    raw = json.dumps(payload, ensure_ascii=False, indent=2)
    path.write_text(raw, encoding="utf-8")
    return path


def default_geo_url(gse: str) -> str:
    return accession_page(gse)


def new_id() -> str:
    return uuid4().hex

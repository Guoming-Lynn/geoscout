from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.models import Base

engine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
    connect_args={"timeout": 30},
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


async def init_db() -> None:
    settings.ensure_dirs()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        await conn.run_sync(_migrate_sqlite_columns)


def _migrate_sqlite_columns(sync_conn) -> None:  # type: ignore[no-untyped-def]
    """Add columns introduced after v0.1 so existing user SQLite files keep data."""
    needed = {
        "query_attempts": [
            ("truncated", "ALTER TABLE query_attempts ADD COLUMN truncated BOOLEAN DEFAULT 0 NOT NULL"),
        ],
        "assessments": [
            ("judge_source", "ALTER TABLE assessments ADD COLUMN judge_source VARCHAR(40) DEFAULT ''"),
            ("actor", "ALTER TABLE assessments ADD COLUMN actor VARCHAR(40) DEFAULT ''"),
            ("quotes_json", "ALTER TABLE assessments ADD COLUMN quotes_json TEXT DEFAULT '[]'"),
            ("support_text", "ALTER TABLE assessments ADD COLUMN support_text TEXT DEFAULT ''"),
            ("clue_only", "ALTER TABLE assessments ADD COLUMN clue_only BOOLEAN DEFAULT 0 NOT NULL"),
            ("qualifying_gsms_json", "ALTER TABLE assessments ADD COLUMN qualifying_gsms_json TEXT DEFAULT '[]'"),
        ],
        "samples": [
            ("group_label", "ALTER TABLE samples ADD COLUMN group_label VARCHAR(200)"),
        ],
    }
    for table, cols in needed.items():
        try:
            rows = sync_conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        except Exception:
            continue
        if not rows:
            continue
        existing = {row[1] for row in rows}
        for name, ddl in cols:
            if name not in existing:
                sync_conn.execute(text(ddl))
    _collapse_duplicate_samples(sync_conn)
    _backfill_run_evidence(sync_conn)


def _collapse_duplicate_samples(sync_conn) -> None:  # type: ignore[no-untyped-def]
    """If a copy ever stored duplicate (gse, gsm) rows, keep one and merge fields."""
    try:
        dups = sync_conn.execute(
            text("SELECT gse, gsm FROM samples GROUP BY gse, gsm HAVING COUNT(*) > 1")
        ).fetchall()
    except Exception:
        return
    for gse, gsm in dups:
        rows = sync_conn.execute(
            text("SELECT id FROM samples WHERE gse = :gse AND gsm = :gsm ORDER BY id"),
            {"gse": gse, "gsm": gsm},
        ).fetchall()
        if len(rows) < 2:
            continue
        keep = rows[0][0]
        for extra in rows[1:]:
            sync_conn.execute(
                text(
                    """
                    UPDATE samples SET
                      title = CASE WHEN title = '' THEN (SELECT title FROM samples WHERE id = :extra) ELSE title END,
                      organism = CASE WHEN organism = '' THEN (SELECT organism FROM samples WHERE id = :extra) ELSE organism END,
                      donor_key = COALESCE(donor_key, (SELECT donor_key FROM samples WHERE id = :extra)),
                      group_label = COALESCE(group_label, (SELECT group_label FROM samples WHERE id = :extra))
                    WHERE id = :keep
                    """
                ),
                {"keep": keep, "extra": extra[0]},
            )
            sync_conn.execute(text("DELETE FROM samples WHERE id = :id"), {"id": extra[0]})


def _backfill_run_evidence(sync_conn) -> None:  # type: ignore[no-untyped-def]
    """Rebuild run↔evidence links from first-seen run_id and Assessment citations."""
    try:
        sync_conn.execute(text("SELECT 1 FROM run_evidence LIMIT 1"))
        sync_conn.execute(text("SELECT id FROM evidence LIMIT 1"))
    except Exception:
        return

    def _link(run_id: str, eid: str, source_url: str, field_path: str, fetched_at, rebuilt: bool) -> None:
        if not run_id or not eid:
            return
        link_id = hashlib.sha256(f"{run_id}:{eid}".encode("utf-8")).hexdigest()[:32]
        sync_conn.execute(
            text(
                """
                INSERT OR IGNORE INTO run_evidence
                (id, run_id, evidence_id, source_url, field_path, fetched_at, rebuilt)
                VALUES (:id, :run_id, :eid, :url, :path, :fetched, :rebuilt)
                """
            ),
            {
                "id": link_id,
                "run_id": run_id,
                "eid": eid,
                "url": source_url or "",
                "path": field_path or "",
                "fetched": fetched_at,
                "rebuilt": 1 if rebuilt else 0,
            },
        )

    for row in sync_conn.execute(text("SELECT id, run_id, source_url, field_path, fetched_at FROM evidence")).fetchall():
        _link(row[1], row[0], row[2], row[3], row[4], rebuilt=False)
    try:
        assessments = sync_conn.execute(text("SELECT run_id, evidence_ids FROM assessments")).fetchall()
    except Exception:
        return
    for run_id, blob in assessments:
        try:
            eids = json.loads(blob or "[]")
        except Exception:
            continue
        if not isinstance(eids, list):
            continue
        for eid in eids:
            ev = sync_conn.execute(
                text("SELECT source_url, field_path, fetched_at FROM evidence WHERE id = :id"),
                {"id": str(eid)},
            ).fetchone()
            if ev is None:
                continue
            _link(run_id, str(eid), ev[0], ev[1], ev[2], rebuilt=True)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session

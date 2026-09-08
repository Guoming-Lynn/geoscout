import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.connectors.llm import LLMError, LLMProvider
from app.db.models import Assessment, Run, RunDataset
from app.db.session import SessionLocal, init_db
from app.main import app
from app.pipeline.repo import dump, enqueue_job, load
from test_pipeline_mock import _drain


def _gse_from_kwargs(kwargs: dict) -> str:
    user = kwargs.get("user") or ""
    try:
        return str(json.loads(user).get("gse") or "")
    except (TypeError, json.JSONDecodeError):
        return ""


def _fat_complete(original, calls: list[tuple[str, str]]):
    async def fat(self, *args, **kwargs):
        payload, usage = await original(self, *args, **kwargs)
        name = kwargs.get("prompt_name") or ""
        if name in {"assess_dataset", "verify_dataset"}:
            calls.append((name, _gse_from_kwargs(kwargs)))
            fat_usage = {"prompt_tokens": 1800, "completion_tokens": 200, "estimated": False, "source": "mock"}
            if self.on_usage:
                self.on_usage(fat_usage)
            return payload, fat_usage
        return payload, usage

    return fat


@pytest.mark.asyncio
async def test_review_is_assess_then_verify_and_budget_keeps_complete_rows(monkeypatch):
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(LLMProvider, "complete_json", _fat_complete(LLMProvider.complete_json, calls))
    monkeypatch.setattr("app.pipeline.engine.estimate_tokens", lambda _text: 200)
    await init_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1:8000") as client:
        project = (await client.post("/api/projects", json={"original_request": "human atherosclerosis scRNA-seq"})).json()
        run = (await client.post(
            f"/api/projects/{project['id']}/runs",
            json={"mode": "full", "budget": {"max_unique_gse": 3, "max_queries": 4, "max_deep_verify": 3,
                                            "max_tokens": 5500, "max_completion_tokens": 400}},
        )).json()
        rid = run["id"]
    await _drain(rid, limit=200)
    review = [n for n, _ in calls]
    assert review == ["assess_dataset", "verify_dataset"]
    async with SessionLocal() as session:
        db_run = await session.get(Run, rid)
        rows = (await session.execute(select(RunDataset).where(RunDataset.run_id == rid))).scalars().all()
        finals = (await session.execute(select(Assessment).where(Assessment.run_id == rid, Assessment.stage == "final"))).scalars().all()
        usage = load(db_run.token_usage_json, {})
        checkpoint = load(db_run.checkpoint_json, {})
    complete = [r for r in rows if r.verification_status in {"verified", "needs_review"} and any(a.gse == r.gse for a in finals)]
    assert len(complete) == 1
    assert db_run.status == "partial"
    assert "完整核验" in (db_run.stop_reason or "")
    assert checkpoint.get("unfinished") == "llm"
    assert int(usage.get("prompt_tokens") or 0) + int(usage.get("completion_tokens") or 0) >= 4000
    targets = checkpoint.get("deep_targets") or []
    assert len(targets) >= 2
    assert complete[0].gse == calls[0][1]


@pytest.mark.asyncio
async def test_resume_does_not_reassess_completed_candidate(monkeypatch):
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(LLMProvider, "complete_json", _fat_complete(LLMProvider.complete_json, calls))
    monkeypatch.setattr("app.pipeline.engine.estimate_tokens", lambda _text: 200)
    await init_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1:8000") as client:
        project = (await client.post("/api/projects", json={"original_request": "human atherosclerosis scRNA-seq"})).json()
        run = (await client.post(
            f"/api/projects/{project['id']}/runs",
            json={"mode": "full", "budget": {"max_unique_gse": 3, "max_queries": 4, "max_deep_verify": 2,
                                            "max_tokens": 5500, "max_completion_tokens": 400}},
        )).json()
        rid = run["id"]
    await _drain(rid, limit=200)
    first = list(calls)
    done = {gse for name, gse in first if name == "assess_dataset"}
    assert len(first) == 2
    assert first[0][0] == "assess_dataset" and first[1][0] == "verify_dataset"
    async with SessionLocal() as session:
        db_run = await session.get(Run, rid)
        assert db_run.status == "partial"
        budget = load(db_run.budget_json, {})
        budget["max_tokens"] = 40000
        db_run.budget_json = dump(budget)
        db_run.status = "running"
        db_run.stop_reason = ""
        await enqueue_job(session, rid, "assess")
        await session.commit()
    await _drain(rid, limit=200)
    extra = calls[len(first):]
    extra_assess = {gse for name, gse in extra if name == "assess_dataset"}
    assert extra_assess
    assert extra_assess.isdisjoint(done)
    assert extra.count(("assess_dataset", next(iter(extra_assess)))) == 1
    async with SessionLocal() as session:
        rows = (await session.execute(select(RunDataset).where(RunDataset.run_id == rid))).scalars().all()
        finals = {a.gse for a in (await session.execute(select(Assessment).where(Assessment.run_id == rid, Assessment.stage == "final"))).scalars().all()}
    assert done.issubset(finals)
    assert any(r.gse in extra_assess and r.gse in finals for r in rows)


@pytest.mark.asyncio
async def test_model_error_still_records_and_finishes(monkeypatch):
    original = LLMProvider.complete_json

    async def boom(self, *args, **kwargs):
        name = kwargs.get("prompt_name") or ""
        if name == "assess_dataset":
            raise LLMError("forced", retryable=True, kind="output")
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(LLMProvider, "complete_json", boom)
    await init_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1:8000") as client:
        project = (await client.post("/api/projects", json={"original_request": "human atherosclerosis scRNA-seq"})).json()
        run = (await client.post(
            f"/api/projects/{project['id']}/runs",
            json={"mode": "full", "budget": {"max_unique_gse": 2, "max_queries": 4, "max_deep_verify": 1}},
        )).json()
        rid = run["id"]
    await _drain(rid, limit=200)
    async with SessionLocal() as session:
        db_run = await session.get(Run, rid)
        rows = (await session.execute(select(RunDataset).where(RunDataset.run_id == rid))).scalars().all()
    assert db_run.status in {"completed", "partial"}
    assert any("model" in load(r.first_assess_json, {}) for r in rows)

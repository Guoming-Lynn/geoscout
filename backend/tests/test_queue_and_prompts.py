from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from sqlalchemy import select, update

from app.db.models import Job, Project, Run
from app.db.session import SessionLocal, init_db
from app.evidence.store import new_id
from app.main import app
from app.pipeline.engine import Engine, WaitingForCredentials
from app.pipeline.repo import claim_job, dump, enqueue_job
from app.prompts import load_prompt
from app.schemas.spec import Budget
from app.pipeline.spec_parse import heuristic_parse


def test_assess_and_verify_share_json_contract():
    assess = load_prompt("assess_dataset")
    verify = load_prompt("verify_dataset")
    assert "verdict 字段名必须是 verdict" in assess
    assert "verdict 字段名必须是 verdict" in verify
    assert "来源冲突" in assess
    assert "来源冲突" in verify
    assert "你是 GEOScout 的证据审查器" in assess
    assert "你是 GEOScout 的证据审查器" in verify
    assert "首次核验" in assess
    assert "独立复核" in verify
    assert "不要读取或假设首次核验结论" in verify


def test_parse_and_expand_do_not_use_reviewer_prompt():
    parse = load_prompt("parse_research_spec")
    expand = load_prompt("expand_queries")
    assert "不可信外部数据" in parse
    assert "不可信外部数据" in expand
    assert "你是 GEOScout 的证据审查器" not in parse
    assert "你是 GEOScout 的证据审查器" not in expand
    assert "来源冲突" not in parse
    assert "来源冲突" not in expand
    assert "verdict 字段名必须是 verdict" not in parse
    assert "verdict 字段名必须是 verdict" not in expand


@pytest.mark.asyncio
async def test_claim_skips_waiting_and_terminal_runs():
    await init_db()
    async with SessionLocal() as session:
        await session.execute(update(Job).where(Job.status.in_(["queued", "leased"])).values(status="done"))
        project = Project(id=new_id(), name="queue", original_request="x")
        session.add(project)
        await session.flush()
        waiting = Run(id=new_id(), project_id=project.id, status="waiting_for_credentials")
        paused = Run(id=new_id(), project_id=project.id, status="paused")
        live = Run(id=new_id(), project_id=project.id, status="queued")
        done = Run(id=new_id(), project_id=project.id, status="completed")
        session.add_all([waiting, paused, live, done])
        await session.flush()
        session.add(Job(id=new_id(), run_id=waiting.id, step="assess", status="queued"))
        session.add(Job(id=new_id(), run_id=paused.id, step="verify", status="queued"))
        done_job = Job(id=new_id(), run_id=done.id, step="assess", status="queued")
        session.add(done_job)
        live_job = Job(id=new_id(), run_id=live.id, step="plan", status="queued")
        session.add(live_job)
        await session.commit()
        claimed = await claim_job(session, "w", 30)
        await session.commit()
        assert claimed is not None
        assert claimed.run_id == live.id
        leftover = await session.get(Job, done_job.id)
        assert leftover is not None
        assert leftover.status == "cancelled"


@pytest.mark.asyncio
async def test_enqueue_skipped_when_run_finished():
    await init_db()
    async with SessionLocal() as session:
        await session.execute(update(Job).where(Job.status.in_(["queued", "leased"])).values(status="done"))
        project = Project(id=new_id(), name="queue-done", original_request="x")
        session.add(project)
        await session.flush()
        run = Run(id=new_id(), project_id=project.id, status="completed")
        session.add(run)
        await session.flush()
        job = await enqueue_job(session, run.id, "verify")
        await session.commit()
        assert job is None


@pytest.mark.asyncio
async def test_engine_skips_jobs_on_completed_run(monkeypatch):
    run = SimpleNamespace(
        id="r1",
        session_id="s",
        cancel_requested=False,
        pause_requested=False,
        status="completed",
        stop_reason="正常结束",
        stage="exporting",
    )
    job = SimpleNamespace(run_id="r1", step="verify", status="leased", last_error="")
    called = []

    class FakeSession:
        async def get(self, _model, _id):
            return run

    async def fake_event(*_args, **_kwargs):
        return None

    async def boom(_run):
        called.append(1)

    monkeypatch.setattr("app.pipeline.engine.add_event", fake_event)
    engine = Engine(FakeSession(), job, "w")
    engine.step_verify = boom
    await engine.run()
    assert job.status == "cancelled"
    assert job.last_error == "任务已结束，忽略迟到步骤"
    assert called == []


@pytest.mark.asyncio
async def test_assessment_format_repair_runs_once(monkeypatch):
    spec = heuristic_parse("human atherosclerosis scRNA-seq lesion vs control")
    events: list[str] = []

    async def capture(_session, _run_id, message, level="info", payload=None):
        events.append(message)

    monkeypatch.setattr("app.pipeline.engine.add_event", capture)
    run = SimpleNamespace(
        id="r1",
        session_id="s",
        token_usage_json='{"prompt_tokens":0,"completion_tokens":0}',
        budget_json=Budget(max_completion_tokens=512, max_tokens=200000).model_dump_json(),
        spec_snapshot=spec.model_dump_json(),
        config_summary="{}",
        counters_json="{}",
        status="running",
    )
    rd = SimpleNamespace(gse="GSE1")
    job = SimpleNamespace(run_id="r1", step="assess", status="leased", last_error="", payload_json="{}")
    engine = Engine(SimpleNamespace(), job, "w")

    class FakeLLM:
        mock = False
        n = 0

        async def complete_json(self, **_kwargs):
            self.n += 1
            if self.n == 1:
                return (
                    {
                        "inclusion_criteria": [
                            {"field": "organism", "description": "human", "criterion_id": "organism"}
                        ],
                        "evidence_id": [],
                    },
                    {"prompt_tokens": 10, "completion_tokens": 5},
                )
            judgements = [
                {
                    "criterion_id": c.criterion_id,
                    "verdict": "unknown",
                    "evidence_ids": [],
                    "quote": "",
                    "reason": "repair",
                }
                for c in spec.inclusion_criteria
            ]
            return {"judgements": judgements}, {"prompt_tokens": 8, "completion_tokens": 6}

    llm = FakeLLM()
    engine._llm = lambda _run: llm
    engine._guard = lambda _run, _next, **_kw: None
    checked = await engine._complete_assessment(
        run,
        prompt_name="assess_dataset",
        spec=spec,
        rd=rd,
        summary={"title": "x", "taxon": "Homo sapiens", "gdstype": ""},
        evidence=[],
        sample_dicts=[],
        coverage={"complete": True},
    )
    assert llm.n == 2
    assert any("开始格式修复" in m for m in events)
    assert any("格式修复成功" in m for m in events)
    assert not checked.invalid



@pytest.mark.asyncio
async def test_engine_waiting_marks_job_not_queued(monkeypatch):
    run = SimpleNamespace(
        id="r1",
        session_id="s",
        cancel_requested=False,
        pause_requested=False,
        status="running",
        stop_reason="",
        stage="verifying",
    )
    job = SimpleNamespace(run_id="r1", step="assess", status="leased", last_error="")

    class FakeSession:
        async def get(self, _model, _id):
            return run

    async def fake_hydrate(_session_id):
        return None

    async def fake_event(*_args, **_kwargs):
        return None

    async def boom(_run):
        raise WaitingForCredentials()

    monkeypatch.setattr("app.pipeline.engine.hydrate_credentials", fake_hydrate)
    monkeypatch.setattr("app.pipeline.engine.add_event", fake_event)
    engine = Engine(FakeSession(), job, "w")
    engine.step_assess = boom
    await engine.run()
    assert job.status == "waiting_credentials"
    assert run.status == "waiting_for_credentials"


@pytest.mark.asyncio
async def test_resume_does_not_enqueue_stage_name_when_job_exists():
    await init_db()
    async with SessionLocal() as session:
        await session.execute(update(Job).where(Job.status.in_(["queued", "leased"])).values(status="done"))
        project = Project(id=new_id(), name="resume-keep", original_request="x")
        session.add(project)
        await session.flush()
        run = Run(id=new_id(), project_id=project.id, status="paused", stage="verifying", pause_requested=True)
        session.add(run)
        await session.flush()
        existing = Job(id=new_id(), run_id=run.id, step="assess", status="queued")
        session.add(existing)
        await session.commit()
        rid, jid = run.id, existing.id
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1:8000") as client:
        response = await client.post(f"/api/runs/{rid}/resume")
        assert response.status_code == 200
        assert response.json()["status"] == "queued"
    async with SessionLocal() as session:
        jobs = (await session.execute(select(Job).where(Job.run_id == rid))).scalars().all()
        queued = [job for job in jobs if job.status == "queued"]
        assert [job.step for job in queued] == ["assess"]
        assert queued[0].id == jid
        assert all(job.step != "verifying" for job in jobs)


@pytest.mark.asyncio
async def test_resume_without_jobs_maps_verifying_to_assess():
    await init_db()
    async with SessionLocal() as session:
        await session.execute(update(Job).where(Job.status.in_(["queued", "leased"])).values(status="done"))
        project = Project(id=new_id(), name="resume-map", original_request="x")
        session.add(project)
        await session.flush()
        run = Run(
            id=new_id(),
            project_id=project.id,
            status="paused",
            stage="verifying",
            pause_requested=True,
            checkpoint_json=dump({"deep_targets": ["GSE1"]}),
        )
        session.add(run)
        await session.commit()
        rid = run.id
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1:8000") as client:
        response = await client.post(f"/api/runs/{rid}/resume")
        assert response.status_code == 200
    async with SessionLocal() as session:
        jobs = (await session.execute(select(Job).where(Job.run_id == rid, Job.status == "queued"))).scalars().all()
        assert [job.step for job in jobs] == ["assess"]


@pytest.mark.asyncio
async def test_cancel_paused_run_finishes_without_worker():
    await init_db()
    async with SessionLocal() as session:
        await session.execute(update(Job).where(Job.status.in_(["queued", "leased"])).values(status="done"))
        project = Project(id=new_id(), name="cancel-paused", original_request="x")
        session.add(project)
        await session.flush()
        run = Run(id=new_id(), project_id=project.id, status="paused", stage="verifying")
        session.add(run)
        await session.flush()
        session.add(Job(id=new_id(), run_id=run.id, step="assess", status="queued"))
        await session.commit()
        rid = run.id
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1:8000") as client:
        response = await client.post(f"/api/runs/{rid}/cancel")
        assert response.status_code == 200
        assert response.json()["status"] == "cancelled"
    async with SessionLocal() as session:
        db_run = await session.get(Run, rid)
        jobs = (await session.execute(select(Job).where(Job.run_id == rid))).scalars().all()
        assert db_run is not None and db_run.status == "cancelled"
        assert all(job.status == "cancelled" for job in jobs)

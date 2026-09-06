from types import SimpleNamespace

import pytest

from sqlalchemy import update

from app.db.models import Job, Project, Run
from app.db.session import SessionLocal, init_db
from app.evidence.store import new_id
from app.pipeline.engine import Engine, WaitingForCredentials
from app.pipeline.repo import claim_job, enqueue_job
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
    assert "首次核验" in assess
    assert "独立复核" in verify
    assert "不要读取或假设首次核验结论" in verify


@pytest.mark.asyncio
async def test_claim_skips_waiting_and_terminal_runs():
    await init_db()
    async with SessionLocal() as session:
        await session.execute(update(Job).where(Job.status.in_(["queued", "leased"])).values(status="done"))
        project = Project(id=new_id(), name="queue", original_request="x")
        session.add(project)
        await session.flush()
        waiting = Run(id=new_id(), project_id=project.id, status="waiting_for_credentials")
        live = Run(id=new_id(), project_id=project.id, status="queued")
        done = Run(id=new_id(), project_id=project.id, status="completed")
        session.add_all([waiting, live, done])
        await session.flush()
        session.add(Job(id=new_id(), run_id=waiting.id, step="assess", status="queued"))
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
    engine._guard = lambda _run, _next: None
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

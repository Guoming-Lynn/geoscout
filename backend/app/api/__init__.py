from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.llm import LLMProvider
from app.core.config import settings
from app.core.credentials import SessionCredentials, store
from app.core.security import SESSION_COOKIE, require_internal_token
from app.db.models import Assessment, Dataset, Event, Export, Job, Override, Project, QueryAttempt, Run, RunDataset, Sample
from app.db.session import get_session
from app.evidence.store import evidence_bundle, new_id
from app.exporters.service import create_export
from app.pipeline.engine import parse_spec_with_optional_llm
from app.pipeline.repo import add_event, dump, enqueue_job, load
from app.pipeline.spec_parse import heuristic_parse
from app.schemas.spec import (
    Budget,
    ConnectionConfigIn,
    ExportIn,
    OverrideIn,
    ProjectCreate,
    ResearchSpec,
    RunCreate,
)
from app.api.deps import browser_guard, session_creds
from app.connectors.llm import PROMPT_VERSIONS

router = APIRouter(prefix="/api", dependencies=[Depends(browser_guard)])
internal = APIRouter(prefix="/internal")


def _run_view(run: Run) -> dict:
    return {
        "id": run.id,
        "project_id": run.project_id,
        "mode": run.mode,
        "status": run.status,
        "stage": run.stage,
        "stop_reason": run.stop_reason,
        "counters": load(run.counters_json, {}),
        "token_usage": load(run.token_usage_json, {}),
        "budget": load(run.budget_json, {}),
        "error_message": run.error_message,
        "duplicate_billing_risk": run.duplicate_billing_risk,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "spec": load(run.spec_snapshot, {}),
        "config": {k: v for k, v in load(run.config_summary, {}).items() if "key" not in k.lower()},
    }


@router.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "version": "0.1.0",
        "ncbi_mode": settings.ncbi_mode,
        "llm_mode": settings.llm_mode,
        "demo": settings.demo_allowed(),
        "host": settings.host,
    }


@router.get("/connections")
async def connection_status(creds: SessionCredentials = Depends(session_creds)) -> dict:
    return creds.public_view()


@router.put("/connections")
async def save_connection(
    body: ConnectionConfigIn,
    creds: SessionCredentials = Depends(session_creds),
) -> dict:
    store.update(
        creds.session_id,
        llm_provider=body.llm_provider,
        llm_base_url=body.llm_base_url.rstrip("/"),
        llm_model=body.llm_model,
        llm_api_key=body.llm_api_key if body.llm_api_key is not None else creds.llm_api_key,
        llm_timeout_s=body.llm_timeout_s,
        llm_input_price_per_mtok=body.llm_input_price_per_mtok,
        llm_output_price_per_mtok=body.llm_output_price_per_mtok,
        ncbi_api_key=body.ncbi_api_key if body.ncbi_api_key is not None else creds.ncbi_api_key,
        ncbi_email=body.ncbi_email if body.ncbi_email is not None else creds.ncbi_email,
        ncbi_tool=body.ncbi_tool or creds.ncbi_tool,
    )
    return store.get_or_create(creds.session_id).public_view()


@router.post("/connections/test")
async def test_connection(
    body: ConnectionConfigIn,
    creds: SessionCredentials = Depends(session_creds),
) -> dict:
    await save_connection(body, creds)
    latest = store.get_or_create(creds.session_id)
    mock = settings.llm_mode == "mock"
    provider = LLMProvider(latest, mock=mock)
    return await provider.test_connection()


@router.get("/projects")
async def list_projects(db: AsyncSession = Depends(get_session)) -> list[dict]:
    rows = (await db.execute(select(Project).order_by(Project.created_at.desc()))).scalars().all()
    return [
        {
            "id": p.id,
            "name": p.name,
            "original_request": p.original_request,
            "spec": load(p.spec_json, {}),
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in rows
    ]


@router.post("/projects")
async def create_project(body: ProjectCreate, db: AsyncSession = Depends(get_session)) -> dict:
    spec = heuristic_parse(body.original_request)
    name = body.name or (body.original_request[:40] or "未命名课题")
    project = Project(
        id=new_id(),
        name=name,
        original_request=body.original_request,
        spec_json=spec.model_dump_json(),
    )
    db.add(project)
    await db.commit()
    return {"id": project.id, "name": project.name, "spec": spec.model_dump()}


@router.post("/projects/{project_id}/spec/parse")
async def parse_spec(
    project_id: str,
    creds: SessionCredentials = Depends(session_creds),
    db: AsyncSession = Depends(get_session),
) -> dict:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "课题不存在")
    spec = await parse_spec_with_optional_llm(project.original_request, creds.session_id)
    project.spec_json = spec.model_dump_json()
    await db.commit()
    questions = spec.unresolved_questions[:3]
    return {"spec": spec.model_dump(), "questions": questions, "llm_used": settings.llm_mode == "mock" or creds.has_llm_key()}


@router.put("/projects/{project_id}/spec")
async def save_spec(project_id: str, body: ResearchSpec, db: AsyncSession = Depends(get_session)) -> dict:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "课题不存在")
    project.spec_json = body.model_dump_json()
    await db.commit()
    return {"spec": body.model_dump()}


@router.post("/projects/{project_id}/runs")
async def create_run(
    project_id: str,
    body: RunCreate,
    creds: SessionCredentials = Depends(session_creds),
    db: AsyncSession = Depends(get_session),
) -> dict:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "课题不存在")
    if body.demo and not settings.demo_allowed():
        raise HTTPException(400, "演示模式未开启。真实检索失败时也不会改用演示数据。")
    spec = ResearchSpec.model_validate(load(project.spec_json, {}))
    if not spec.original_request:
        spec.original_request = project.original_request
    budget = body.budget or Budget()
    if body.mode == "manual_query":
        if not body.manual_query:
            raise HTTPException(400, "手工检索需要英文检索词")
        budget.max_rounds = 1
    run = Run(
        id=new_id(),
        project_id=project.id,
        session_id=creds.session_id,
        mode=body.mode,
        spec_snapshot=spec.model_dump_json(),
        budget_json=budget.model_dump_json(),
        status="queued",
        stage="planning",
        prompt_versions=dump(PROMPT_VERSIONS),
        config_summary=dump(
            {
                "manual_query": body.manual_query,
                "one_click": body.one_click,
                "demo": bool(body.demo),
                "ncbi_mode": "mock" if body.demo else settings.ncbi_mode,
                "llm_mode": settings.llm_mode,
                "llm_model": creds.llm_model,
                "llm_base_url": creds.llm_base_url,
            }
        ),
    )
    db.add(run)
    await enqueue_job(db, run.id, "plan")
    await add_event(db, run.id, "任务已排队")
    await db.commit()
    await db.refresh(run)
    return _run_view(run)


@router.get("/projects/{project_id}/runs")
async def list_runs(project_id: str, db: AsyncSession = Depends(get_session)) -> list[dict]:
    rows = (
        await db.execute(select(Run).where(Run.project_id == project_id).order_by(Run.created_at.desc()))
    ).scalars().all()
    return [_run_view(r) for r in rows]


@router.get("/runs/{run_id}")
async def get_run(run_id: str, db: AsyncSession = Depends(get_session)) -> dict:
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(404, "任务不存在")
    return _run_view(run)


@router.post("/runs/{run_id}/pause")
async def pause_run(run_id: str, db: AsyncSession = Depends(get_session)) -> dict:
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(404, "任务不存在")
    run.pause_requested = True
    run.status = "pausing"
    await add_event(db, run.id, "已请求暂停，将在当前原子步骤结束后生效")
    await db.commit()
    return _run_view(run)


@router.post("/runs/{run_id}/resume")
async def resume_run(run_id: str, db: AsyncSession = Depends(get_session)) -> dict:
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(404, "任务不存在")
    run.pause_requested = False
    if run.status in {"paused", "waiting_for_credentials"}:
        run.status = "queued"
        run.stop_reason = ""
        waiting = (
            await db.execute(select(Job).where(Job.run_id == run.id, Job.status == "waiting_credentials"))
        ).scalars().all()
        for job in waiting:
            job.status = "queued"
            job.last_error = ""
        if not waiting:
            await enqueue_job(db, run.id, "search") if run.stage == "searching" else await enqueue_job(
                db, run.id, run.stage if run.stage != "planning" else "plan"
            )
        await add_event(db, run.id, "任务已恢复")
    await db.commit()
    return _run_view(run)


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str, db: AsyncSession = Depends(get_session)) -> dict:
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(404, "任务不存在")
    run.cancel_requested = True
    await add_event(db, run.id, "已请求取消。模型若已发出请求，费用无法退回。")
    await db.commit()
    return _run_view(run)


@router.get("/runs/{run_id}/events")
async def sse_events(run_id: str, request: Request, db: AsyncSession = Depends(get_session)) -> StreamingResponse:
    last = request.headers.get("last-event-id") or request.query_params.get("last_event_id") or "0"

    async def gen():
        cursor = int(last or 0)
        while True:
            async with db.bind.connect() as _conn:  # keep session usable
                pass
            rows = (
                await db.execute(
                    select(Event).where(Event.run_id == run_id, Event.id > cursor).order_by(Event.id.asc())
                )
            ).scalars().all()
            for row in rows:
                cursor = row.id
                payload = {
                    "id": row.id,
                    "message": row.message,
                    "level": row.level,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                yield f"id: {row.id}\nevent: log\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            run = await db.get(Run, run_id)
            if run and run.status in {"completed", "partial", "failed", "cancelled"}:
                yield f"event: done\ndata: {json.dumps({'status': run.status})}\n\n"
                break
            await asyncio.sleep(0.6)

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/runs/{run_id}/queries")
async def list_queries(run_id: str, db: AsyncSession = Depends(get_session)) -> list[dict]:
    rows = (
        await db.execute(select(QueryAttempt).where(QueryAttempt.run_id == run_id).order_by(QueryAttempt.round_no))
    ).scalars().all()
    return [
        {
            "id": q.id,
            "term": q.term,
            "round_no": q.round_no,
            "source": q.source,
            "hit_count": q.hit_count,
            "new_unique_gse": q.new_unique_gse,
            "query_translation": q.query_translation,
            "status": q.status,
            "truncated": bool(q.truncated),
            "error_message": q.error_message,
        }
        for q in rows
    ]


@router.get("/runs/{run_id}/datasets")
async def list_datasets(
    run_id: str,
    category: str | None = None,
    q: str | None = None,
    offset: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_session),
) -> dict:
    stmt = select(RunDataset).where(RunDataset.run_id == run_id)
    if category:
        stmt = stmt.where(RunDataset.category == category)
    rows = (await db.execute(stmt)).scalars().all()
    items = []
    for rd in rows:
        ds = await db.get(Dataset, rd.gse)
        title = ds.title if ds else ""
        if q and q.lower() not in (rd.gse + title).lower():
            continue
        items.append(
            {
                "gse": rd.gse,
                "title": title,
                "taxon": ds.taxon if ds else "",
                "gdstype": ds.gdstype if ds else "",
                "n_samples": ds.n_samples if ds else None,
                "category": rd.category,
                "verification_status": rd.verification_status,
                "reason": rd.reason,
                "hard_unknowns": rd.hard_unknowns,
                "soft_score": rd.soft_score,
                "independent_donors": rd.independent_donors,
                "processed_data": rd.processed_data,
            }
        )
    total = len(items)
    return {"total": total, "items": items[offset : offset + limit]}


@router.get("/runs/{run_id}/datasets/{gse}")
async def dataset_detail(run_id: str, gse: str, db: AsyncSession = Depends(get_session)) -> dict:
    rd = (
        await db.execute(select(RunDataset).where(RunDataset.run_id == run_id, RunDataset.gse == gse.upper()))
    ).scalar_one_or_none()
    if not rd:
        raise HTTPException(404, "结果不存在")
    ds = await db.get(Dataset, rd.gse)
    samples = (await db.execute(select(Sample).where(Sample.gse == rd.gse))).scalars().all()
    assessments = (
        await db.execute(select(Assessment).where(Assessment.run_id == run_id, Assessment.gse == rd.gse))
    ).scalars().all()
    evidence = await evidence_bundle(db, run_id, rd.gse)
    ov = (
        await db.execute(select(Override).where(Override.run_id == run_id, Override.gse == rd.gse))
    ).scalar_one_or_none()
    return {
        "gse": rd.gse,
        "url": f"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={rd.gse}",
        "dataset": {
            "title": ds.title if ds else "",
            "summary": ds.summary if ds else "",
            "taxon": ds.taxon if ds else "",
            "gdstype": ds.gdstype if ds else "",
            "gpl": ds.gpl if ds else "",
            "n_samples": ds.n_samples if ds else None,
            "pubmed_ids": load(ds.pubmed_ids, []) if ds else [],
            "ftplink": ds.ftplink if ds else "",
        },
        "run_dataset": {
            "category": rd.category,
            "verification_status": rd.verification_status,
            "reason": rd.reason,
            "concerns": rd.concerns,
            "gsm_count": rd.gsm_count,
            "independent_donors": rd.independent_donors,
            "donors_per_group": load(rd.donors_per_group_json, {}),
            "processed_data": rd.processed_data,
            "raw_data": rd.raw_data,
            "hard_unknowns": rd.hard_unknowns,
            "soft_score": rd.soft_score,
            "conflict": load(rd.conflict_json, []),
            "model_output_invalid": rd.model_output_invalid,
            "applicable_gsms": sorted(
                set.intersection(
                    *[
                        {str(gsm) for gsm in load(getattr(a, "qualifying_gsms_json", None), []) if gsm}
                        for a in assessments
                        if a.stage == "final" and load(getattr(a, "qualifying_gsms_json", None), [])
                    ]
                )
            )
            if any(a.stage == "final" and load(getattr(a, "qualifying_gsms_json", None), []) for a in assessments)
            else [],
            "unknown_hard": [
                a.criterion_id for a in assessments if a.stage == "final" and a.verdict == "unknown"
            ],
        },
        "samples": [
            {
                "gsm": s.gsm,
                "title": s.title,
                "organism": s.organism,
                "source_name": s.source_name,
                "donor_key": s.donor_key,
                "characteristics": load(s.characteristics_json, []),
                "coverage_incomplete": s.coverage_incomplete,
            }
            for s in samples
        ],
        "assessments": [
            {
                "criterion_id": a.criterion_id,
                "verdict": a.verdict,
                "stage": a.stage,
                "reason": a.reason,
                "quote": a.quote,
                "evidence_ids": load(a.evidence_ids, []),
                "judge_source": a.judge_source,
                "actor": a.actor,
                "support_text": getattr(a, "support_text", "") or "",
                "clue_only": bool(getattr(a, "clue_only", False)),
                "qualifying_gsms": load(getattr(a, "qualifying_gsms_json", None), []),
            }
            for a in sorted(assessments, key=lambda x: (0 if x.stage == "final" else 1, x.criterion_id, x.stage))
        ],
        "evidence": evidence,
        "override": None
        if not ov
        else {
            "previous_category": ov.previous_category,
            "new_category": ov.new_category,
            "reason": ov.reason,
            "created_at": ov.created_at.isoformat() if ov.created_at else None,
        },
    }


@router.post("/runs/{run_id}/datasets/{gse}/override")
async def override_dataset(run_id: str, gse: str, body: OverrideIn, db: AsyncSession = Depends(get_session)) -> dict:
    rd = (
        await db.execute(select(RunDataset).where(RunDataset.run_id == run_id, RunDataset.gse == gse.upper()))
    ).scalar_one_or_none()
    if not rd:
        raise HTTPException(404, "结果不存在")
    item = Override(
        id=new_id(),
        run_id=run_id,
        gse=rd.gse,
        previous_category=rd.category,
        new_category=body.category,
        reason=body.reason,
    )
    rd.category = body.category
    db.add(item)
    db.add(
        Assessment(
            id=new_id(),
            run_id=run_id,
            gse=rd.gse,
            criterion_id="override",
            verdict="unknown",
            stage="override",
            reason=f"原类别 {item.previous_category} → {item.new_category}。{body.reason}",
            judge_source="human",
            actor="human",
        )
    )
    await add_event(db, run_id, f"{rd.gse} 人工覆盖为 {body.category}")
    await db.commit()
    return {"gse": rd.gse, "category": rd.category, "machine_previous": item.previous_category}


@router.post("/runs/{run_id}/exports")
async def export_run(run_id: str, body: ExportIn, db: AsyncSession = Depends(get_session)) -> dict:
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(404, "任务不存在")
    item = await create_export(db, run, include_json=body.include_json)
    await db.commit()
    await db.refresh(item)
    return {
        "id": item.id,
        "filename": item.filename,
        "complete": item.complete,
        "download": f"/api/exports/{item.id}/download",
        "status": run.status,
        "stop_reason": run.stop_reason,
    }


@router.get("/exports/{export_id}/download")
async def download_export(export_id: str, db: AsyncSession = Depends(get_session)) -> FileResponse:
    item = await db.get(Export, export_id)
    if not item:
        raise HTTPException(404, "导出不存在")
    return FileResponse(item.path, filename=item.filename, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@internal.get("/credentials/{session_id}")
async def internal_credentials(session_id: str, _: None = Depends(require_internal_token)) -> dict:
    creds = store.get(session_id)
    if not creds:
        raise HTTPException(404, "凭据不在内存中")
    return {
        "llm_base_url": creds.llm_base_url,
        "llm_model": creds.llm_model,
        "llm_api_key": creds.llm_api_key,
        "llm_timeout_s": creds.llm_timeout_s,
        "ncbi_api_key": creds.ncbi_api_key,
        "ncbi_email": creds.ncbi_email,
        "ncbi_tool": creds.ncbi_tool,
    }

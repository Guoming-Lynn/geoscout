from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.core.config import settings
from app.core.urls import accession_page
from app.db.models import Assessment, Dataset, DatasetRelation, Export, Override, Project, QueryAttempt, Run, RunDataset, Sample
from app.evidence.store import evidence_bundle, new_id
from app.exporters.audit import write_audit_pack
from app.exporters.excel import safe_filename, write_workbook
from app.pipeline.repo import dump, load
from app.schemas.spec import ResearchSpec


async def build_export_payload(session: AsyncSession, run: Run) -> dict[str, Any]:
    spec = load(run.spec_snapshot, {})
    project = await session.get(Project, run.project_id)
    project_name = project.name if project else ""
    rds = (await session.execute(select(RunDataset).where(RunDataset.run_id == run.id))).scalars().all()
    overrides = (await session.execute(select(Override).where(Override.run_id == run.id))).scalars().all()
    over_map = {o.gse: o for o in overrides}
    candidates = []
    samples_out = []
    assessments_out = []
    for rd in rds:
        ds = await session.get(Dataset, rd.gse)
        summary = load(ds.summary_json, {}) if ds else {}
        rels = (
            await session.execute(select(DatasetRelation).where(DatasetRelation.gse == rd.gse))
        ).scalars().all()
        ov = over_map.get(rd.gse)
        candidates.append(
            {
                "gse": rd.gse,
                "title": ds.title if ds else "",
                "url": accession_page(rd.gse),
                "pubmed_ids": load(ds.pubmed_ids, []) if ds else [],
                "taxon": ds.taxon if ds else "",
                "tissue": "",
                "disease": (spec.get("disease") or [""])[0] if spec.get("disease") else "",
                "gdstype": ds.gdstype if ds else "",
                "gpl": ds.gpl if ds else "",
                "gsm_count": rd.gsm_count,
                "independent_donors": rd.independent_donors,
                "donors_per_group": load(rd.donors_per_group_json, {}),
                "cell_count": rd.cell_count,
                "control_type": "",
                "clinical_fields": spec.get("preferred_metadata") or [],
                "processed_data": rd.processed_data,
                "raw_data": rd.raw_data,
                "category": ov.new_category if ov else rd.category,
                "hard_unknowns": rd.hard_unknowns,
                "soft_score": rd.soft_score,
                "verification_status": rd.verification_status,
                "reason": rd.reason,
                "concerns": rd.concerns,
                "relations": "; ".join(r.target for r in rels),
                "overridden": bool(ov),
            }
        )
        sample_rows = (await session.execute(select(Sample).where(Sample.gse == rd.gse))).scalars().all()
        for s in sample_rows:
            samples_out.append(
                {
                    "gse": rd.gse,
                    "gsm": s.gsm,
                    "title": s.title,
                    "organism": s.organism,
                    "source_name": s.source_name,
                    "donor_key": s.donor_key,
                    "characteristics": load(s.characteristics_json, []),
                    "coverage_incomplete": s.coverage_incomplete,
                }
            )
    assess_rows = (await session.execute(select(Assessment).where(Assessment.run_id == run.id))).scalars().all()
    evid = {row["evidence_id"]: row for row in await evidence_bundle(session, run.id)}
    spec_obj = ResearchSpec.model_validate(spec) if spec else ResearchSpec()
    hard_ids = {c.criterion_id for c in spec_obj.inclusion_criteria if c.priority == "hard"}
    for cand in candidates:
        finals = [a for a in assess_rows if a.gse == cand["gse"] and a.stage == "final"]
        subsets = []
        unknown_hard = []
        for a in finals:
            gsms = load(getattr(a, "qualifying_gsms_json", None), [])
            if gsms:
                subsets.append(set(str(x) for x in gsms))
            if a.verdict == "unknown" and a.criterion_id in hard_ids:
                unknown_hard.append(a.criterion_id)
        cand["applicable_gsms"] = sorted(set.intersection(*subsets)) if subsets else []
        cand["unknown_hard"] = unknown_hard
        missing_eids = []
        for a in finals:
            for eid in load(a.evidence_ids, []):
                if eid and eid not in evid:
                    missing_eids.append(eid)
        if missing_eids:
            cand["concerns"] = (cand.get("concerns") or "") + " 证据关联缺失，需重新核验。"
    for a in assess_rows:
        eids = load(a.evidence_ids, [])
        first = evid.get(eids[0]) if eids else None
        assessments_out.append(
            {
                "gse": a.gse,
                "criterion_id": a.criterion_id,
                "stage": a.stage,
                "verdict": a.verdict,
                "reason": a.reason,
                "quote": a.quote,
                "quotes": load(getattr(a, "quotes_json", None), []),
                "evidence_ids": eids,
                "source_url": (first or {}).get("source_url") or accession_page(a.gse),
                "field_path": (first or {}).get("field_path") or "",
                "judge_source": a.judge_source,
                "actor": a.actor,
                "support_text": getattr(a, "support_text", "") or "",
                "clue_only": bool(getattr(a, "clue_only", False)),
                "qualifying_gsms": load(getattr(a, "qualifying_gsms_json", None), []),
            }
        )
    queries = (await session.execute(select(QueryAttempt).where(QueryAttempt.run_id == run.id))).scalars().all()
    cfg = load(run.config_summary, {})
    return {
        "demo": bool(cfg.get("demo")),
        "project_name": project_name,
        "spec": spec,
        "run": {
            "id": run.id,
            "status": run.status,
            "stop_reason": run.stop_reason,
            "created_at": run.created_at.isoformat() if run.created_at else "",
            "stage": run.stage,
        },
        "candidates": candidates,
        "samples": samples_out,
        "assessments": assessments_out,
        "queries": [
            {
                "round_no": q.round_no,
                "source": q.source,
                "term": q.term,
                "query_translation": q.query_translation,
                "hit_count": q.hit_count,
                "new_unique_gse": q.new_unique_gse,
                "status": q.status,
                "truncated": bool(getattr(q, "truncated", False)),
                "error_message": q.error_message,
                "finished_at": q.finished_at.isoformat() if q.finished_at else "",
            }
            for q in queries
        ],
        "run_info": {
            "software_version": __version__,
            "mode": run.mode,
            "status": run.status,
            "stop_reason": run.stop_reason,
            "budget": load(run.budget_json, {}),
            "counters": load(run.counters_json, {}),
            "token_usage": load(run.token_usage_json, {}),
            "prompt_versions": load(run.prompt_versions, {}),
            "config": {k: v for k, v in cfg.items() if "key" not in k.lower()},
            "duplicate_billing_risk": run.duplicate_billing_risk,
        },
    }


async def create_export(session: AsyncSession, run: Run, *, include_json: bool) -> Export:
    payload = await build_export_payload(session, run)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    short = safe_filename((payload.get("project_name") or "run")[:40])
    filename = f"GEOScout_{short}_{stamp}.xlsx"
    path = settings.export_dir / run.id / filename
    write_workbook(path, payload)
    if include_json:
        write_audit_pack(path.with_suffix(".audit.json"), payload)
    item = Export(
        id=new_id(),
        run_id=run.id,
        path=str(path),
        filename=filename,
        complete=run.status == "completed",
        snapshot_hash="",
        include_json=include_json,
    )
    session.add(item)
    return item

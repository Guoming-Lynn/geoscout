import pytest
from httpx import ASGITransport, AsyncClient

from app.db.models import Assessment, Dataset, Run, RunDataset, Sample
from app.db.session import SessionLocal, init_db
from app.evidence.store import new_id
from app.exporters.excel import read_sheet_maps
from app.exporters.service import create_export
from app.main import app
from app.pipeline.assessment import applicable_gsms
from app.pipeline.repo import dump
from app.pipeline.spec_parse import heuristic_parse
from app.schemas.spec import CriterionJudgement


def _samples():
    return [
        {"gsm": "CASE1", "organism": "Homo sapiens", "library_strategy": "RNA-Seq",
         "characteristics": [{"key": "disease state", "value": "T2D", "raw": "disease state: T2D"}]},
        {"gsm": "CTRL1", "organism": "Homo sapiens", "library_strategy": "RNA-Seq",
         "characteristics": [{"key": "disease state", "value": "non-T2D", "raw": "disease state: non-T2D"}]},
        {"gsm": "MOUSE", "organism": "Mus musculus", "library_strategy": "RNA-Seq",
         "characteristics": [{"key": "disease state", "value": "T2D", "raw": "disease state: T2D"}]},
    ]


def _judgements(spec, *, groups, disease, extra=None):
    extra = extra or {}
    out = []
    for c in spec.inclusion_criteria:
        gsms = extra.get(c.field, extra.get(c.criterion_id))
        if gsms is None:
            if c.field == "groups":
                gsms = groups
            elif c.field == "disease":
                gsms = disease
            else:
                gsms = groups
        out.append(CriterionJudgement(criterion_id=c.criterion_id, verdict="pass", reason="supported", qualifying_gsms=gsms))
    return out


def test_cohort_keeps_controls_when_disease_lists_cases_only():
    spec = heuristic_parse("type 2 diabetes human RNA-seq disease and control")
    samples = _samples()[:2]
    js = _judgements(spec, groups=["CASE1", "CTRL1"], disease=["CASE1"])
    assert applicable_gsms(spec, js, samples) == ["CASE1", "CTRL1"]


def test_mixed_species_control_is_not_kept():
    spec = heuristic_parse("type 2 diabetes human RNA-seq disease and control")
    js = _judgements(spec, groups=["CASE1", "MOUSE"], disease=["CASE1", "MOUSE"])
    assert "MOUSE" not in applicable_gsms(spec, js, _samples())


def test_disjoint_custom_treatment_cannot_keep_unrelated_groups():
    spec = heuristic_parse("type 2 diabetes human RNA-seq disease and control")
    from app.schemas.spec import Criterion
    spec.inclusion_criteria.append(Criterion(
        criterion_id="treatment", field="treatment", description="untreated", user_text="untreated", priority="hard", value=None,
    ))
    samples = [
        {**_samples()[0], "gsm": "GSM1", "characteristics": [
            {"key": "disease state", "value": "T2D", "raw": "disease state: T2D"},
        ]},
        {**_samples()[1], "gsm": "GSM2", "characteristics": [
            {"key": "disease state", "value": "non-T2D", "raw": "disease state: non-T2D"},
        ]},
        {"gsm": "GSM3", "organism": "Homo sapiens", "library_strategy": "RNA-Seq",
         "characteristics": [
             {"key": "disease state", "value": "T2D", "raw": "disease state: T2D"},
             {"key": "treatment", "value": "untreated", "raw": "treatment: untreated"},
         ]},
    ]
    js = _judgements(spec, groups=["GSM1", "GSM2"], disease=["GSM1"], extra={"treatment": ["GSM3"]})
    for item in js:
        item.quote = "supported"
        item.support_text = "supported"
    from app.pipeline.assessment import _restrict_to_common_subset
    from app.pipeline.screening import classify
    result = _restrict_to_common_subset(spec, js, samples)
    groups = next(j for j in result if j.criterion_id == "groups")
    assert groups.verdict == "unknown"
    assert applicable_gsms(spec, result, samples) == []
    cat, _ = classify(spec, result, verified=True, conflict=False, model_invalid=False)
    assert cat != "recommended"


def test_disjoint_age_and_group_subsets_cannot_keep_controls_without_age():
    spec = heuristic_parse("type 2 diabetes human RNA-seq disease and control")
    from app.schemas.spec import Criterion
    spec.inclusion_criteria.append(Criterion(criterion_id="meta_age", field="age", description="age", user_text="age", priority="hard", value=None))
    samples = [
        {**_samples()[0], "characteristics": _samples()[0]["characteristics"] + [{"key": "age", "value": "55", "raw": "age: 55"}]},
        _samples()[1],
    ]
    js = _judgements(spec, groups=["CASE1", "CTRL1"], disease=["CASE1"], extra={"age": ["CASE1"]})
    from app.pipeline.assessment import _restrict_to_common_subset
    result = _restrict_to_common_subset(spec, js, samples)
    groups = next(j for j in result if j.criterion_id == "groups")
    assert groups.verdict == "unknown"
    assert "CTRL1" not in applicable_gsms(spec, result, samples)


@pytest.mark.asyncio
async def test_api_and_excel_share_control_cohort():
    await init_db()
    spec = heuristic_parse("type 2 diabetes human RNA-seq disease and control")
    pid, rid, gse = new_id(), new_id(), f"GSE{new_id()[:8].upper()}"
    async with SessionLocal() as session:
        from app.db.models import Project
        session.add(Project(id=pid, name="cohort", original_request="type 2 diabetes human RNA-seq disease and control", spec_json=spec.model_dump_json()))
        run = Run(id=rid, project_id=pid, status="completed", spec_snapshot=dump(spec.model_dump()), mode="full")
        session.add(run)
        session.add(Dataset(gse=gse, title="t2d", taxon="Homo sapiens", gdstype="Expression profiling by high throughput sequencing"))
        await session.flush()
        session.add(RunDataset(id=new_id(), run_id=run.id, gse=gse, category="needs_review", verification_status="verified"))
        for gsm, group in [("CASE1", "T2D"), ("CTRL1", "non-T2D")]:
            session.add(Sample(id=new_id(), gse=gse, gsm=gsm, organism="Homo sapiens", library_strategy="RNA-Seq",
                                characteristics_json=dump([{"key": "disease state", "value": group, "raw": f"disease state: {group}"}])))
        await session.flush()
        for c in spec.inclusion_criteria:
            gsms = ["CASE1"] if c.field == "disease" else ["CASE1", "CTRL1"]
            session.add(Assessment(id=new_id(), run_id=run.id, gse=gse, criterion_id=c.criterion_id, verdict="pass",
                                   stage="final", reason="ok", qualifying_gsms_json=dump(gsms)))
        await session.commit()
        export = await create_export(session, run, include_json=True)
        await session.commit()
        excel_rows = read_sheet_maps(export.path, "Candidates")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1:8000") as client:
        detail = (await client.get(f"/api/runs/{rid}/datasets/{gse}")).json()
    api_gsms = set(detail["run_dataset"]["applicable_gsms"])
    excel_gsms = {part.strip() for part in str(excel_rows[0].get("采用GSM子集") or "").split(",") if part.strip()}
    assert api_gsms == {"CASE1", "CTRL1"}
    assert excel_gsms == api_gsms

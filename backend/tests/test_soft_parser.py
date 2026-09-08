from pathlib import Path

import pytest
from sqlalchemy import select

from app.db.models import Job, Project, Run, Sample
from app.db.session import SessionLocal, init_db
from app.evidence.soft_parser import count_independent_donors, parse_soft_text, series_as_dict
from app.evidence.store import evidence_bundle, new_id
from app.pipeline.assessment import _restrict_to_common_subset
from app.pipeline.engine import Engine, _sample_dicts
from app.pipeline.repo import dump, load, upsert_dataset, upsert_run_dataset
from app.pipeline.screening import classify
from app.pipeline.spec_parse import _fill_criteria
from app.pipeline.source import source_kind
from app.schemas.spec import CriterionJudgement, ResearchSpec

FIXTURE = Path(__file__).parent / "fixtures" / "GSE1000_metadata.soft"
CULTURED = Path(__file__).parent / "fixtures" / "GSE999001_metadata.soft"


def test_soft_skips_tables_and_counts_donors():
    doc = parse_soft_text(FIXTURE.read_text(encoding="utf-8"))
    parsed = series_as_dict(doc)
    assert parsed["gse"] == "GSE1000"
    assert doc.tables_skipped == 1
    samples = parsed["samples"]
    assert len(samples) == 3
    # D1 appears twice and must not be counted twice.
    human = [s for s in samples if s["organism"] == "Homo sapiens"]
    assert count_independent_donors(human) == 1
    organisms = {s["organism"] for s in samples}
    assert organisms == {"Homo sapiens", "Mus musculus"}


def test_truncation_flag():
    doc = parse_soft_text(FIXTURE.read_text(encoding="utf-8"), max_samples=1)
    assert doc.truncated
    assert doc.truncate_reason == "max_samples"
    assert len(doc.samples) == 1


def test_growth_protocol_is_copied_into_sample_protocol():
    doc = parse_soft_text(CULTURED.read_text(encoding="utf-8"))
    sample = series_as_dict(doc)["samples"][0]
    assert sample["source_name"] == "PBMC"
    assert "cultured in vitro for 14 days" in sample["protocol"]
    assert "cultured in vitro for 14 days" in sample["protocol_fields"]["growth_protocol"]
    assert source_kind(sample) is None


@pytest.mark.asyncio
async def test_soft_protocol_survives_store_and_blocks_primary_pass():
    await init_db()
    pid, rid, gse = new_id(), new_id(), "GSE999001"
    spec = ResearchSpec(sample_source="primary", organisms=["Homo sapiens"], assay_types=["rna_seq_generic"])
    _fill_criteria(spec)
    async with SessionLocal() as session:
        session.add(Project(id=pid, name="cultured-pbmc", original_request="primary PBMC RNA-seq"))
        session.add(Run(
            id=rid, project_id=pid, status="running", stage="fetching", mode="full",
            spec_snapshot=dump(spec.model_dump()), budget_json=dump({"max_deep_verify": 1, "max_unique_gse": 5}),
        ))
        await upsert_dataset(session, {
            "accession": gse, "title": "cultured pbmc", "summary": "", "taxon": "Homo sapiens",
            "gdstype": "Expression profiling by high throughput sequencing",
        })
        await upsert_run_dataset(session, rid, gse, "term")
        job = Job(id=new_id(), run_id=rid, step="deep_fetch", status="leased", payload_json=dump({"index": 0}))
        session.add(job)
        await session.commit()
        job2 = await session.get(Job, job.id)
        run = await session.get(Run, rid)
        await Engine(session, job2, "test-worker").step_deep_fetch(run)
        await session.commit()
        stored = (await session.execute(select(Sample).where(Sample.gse == gse))).scalars().all()
        rows = await _sample_dicts(session, gse)
        evid = await evidence_bundle(session, rid, gse)
    assert stored
    assert any("cultured in vitro" in str(load(s.attrs_json, {}).get("protocol") or "") for s in stored)
    assert rows[0]["source_name"] == "PBMC"
    assert "cultured in vitro" in rows[0]["protocol"]
    assert source_kind(rows[0]) is None
    assert any("cultured in vitro" in str(e.get("text") or "") for e in evid)
    j = CriterionJudgement(criterion_id="sample_source", verdict="pass", quote="PBMC", qualifying_gsms=[rows[0]["gsm"]])
    restricted = _restrict_to_common_subset(spec, [j], rows)
    assert restricted[0].verdict == "unknown"
    cat, _ = classify(spec, restricted, verified=True, conflict=False, model_invalid=False)
    assert cat != "recommended"


def test_extract_protocol_ivt_does_not_block_primary():
    soft = """^SERIES = GSE999002
!Series_title = Primary PBMC RNA-seq
!Series_geo_accession = GSE999002
^SAMPLE = GSMIVT1
!Sample_title = Primary PBMC
!Sample_geo_accession = GSMIVT1
!Sample_organism_ch1 = Homo sapiens
!Sample_source_name_ch1 = PBMC
!Sample_library_strategy = RNA-Seq
!Sample_extract_protocol_ch1 = RNA was amplified by in vitro transcription.
!Sample_characteristics_ch1 = tissue: blood
"""
    sample = series_as_dict(parse_soft_text(soft))["samples"][0]
    assert sample["source_name"] == "PBMC"
    assert "in vitro transcription" in sample["protocol"]
    assert "in vitro transcription" in sample["protocol_fields"]["extract_protocol"]
    assert "growth_protocol" not in sample["protocol_fields"]
    assert source_kind(sample) == "primary"

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from httpx import ASGITransport, AsyncClient

from app.db.models import Base
from app.db.session import _migrate_sqlite_columns, init_db
from app.main import app
from app.pipeline.mock_ncbi import MockNCBIClient
from app.pipeline.ranking import relevance, select_deep_targets
from app.pipeline.spec_parse import heuristic_parse, _fill_criteria
from app.schemas.spec import ResearchSpec
from test_pipeline_mock import _drain


def test_hard_tissue_prefers_sample_title_over_background_mention():
    spec = heuristic_parse("human Alzheimer disease primary brain RNA-seq")
    spec.tissues = ["brain"]
    spec.tissue_required = True
    spec.sample_source = "primary"
    _fill_criteria(spec)
    brain = relevance(spec, {"title": "Dentate gyrus biopsies from Alzheimer patients and controls"}, [])
    blood = relevance(spec, {"title": "Whole blood transcriptome in Alzheimer disease", "summary": "Brain pathology is discussed."}, [])
    heart = relevance(spec, {"title": "Heart biopsy RNA-seq", "summary": "Includes Alzheimer brain as motivation."}, [])
    unknown = relevance(spec, {"title": "Transcriptome of undetermined tissue Alzheimer cohort"}, [])
    assert "target_tissue_sample_evidence" in brain["reasons"] or "target_tissue_in_title" in brain["reasons"]
    assert "target_tissue_in_summary" in blood["reasons"] or "conflicting_tissue_in_title" in blood["reasons"]
    assert brain["score"] > blood["score"] > heart["score"] or brain["score"] > heart["score"]
    assert brain["score"] > unknown["score"]


def test_primary_spec_downranks_cell_line_without_english_model_in_request():
    spec = ResearchSpec(original_request="人原代脑组织转录组", disease=["Alzheimer disease"], tissues=["brain"], sample_source="primary", tissue_required=True)
    _fill_criteria(spec)
    primary = relevance(spec, {"title": "Postmortem cortex biopsies from Alzheimer patients"}, [])
    line = relevance(spec, {"title": "HEK293T cell line model of Alzheimer disease"}, [])
    assert primary["score"] > line["score"]
    assert "source_mismatch_model" in line["reasons"]


def test_diversity_does_not_replace_high_relevance_with_off_tissue():
    spec = heuristic_parse("human Alzheimer disease primary brain RNA-seq")
    spec.tissues = ["brain"]
    spec.tissue_required = True
    _fill_criteria(spec)
    summaries = {
        "GSEB1": {"title": "Dentate gyrus biopsies Alzheimer patients and controls"},
        "GSEB2": {"title": "Hippocampus biopsies Alzheimer patients and controls"},
        "GSEBLOOD": {"title": "Whole blood Alzheimer transcriptome"},
    }
    rows = []
    for gse, summary in summaries.items():
        score = relevance(spec, summary, [])
        rows.append(SimpleNamespace(gse=gse, verification_status="summary_screened",
                                   first_assess_json=json.dumps({"selection": score})))
    picked = select_deep_targets(rows, summaries, 2)
    assert picked[0] in {"GSEB1", "GSEB2"}
    assert "GSEBLOOD" not in picked


def test_patient_comparison_ranks_above_unknown_method():
    spec = heuristic_parse("human breast cancer RNA-seq disease control")
    good = relevance(spec, {"title": "Breast cancer patients and matched healthy controls"}, [])
    vague = relevance(spec, {"title": "A new single-cell barcoding method", "summary": "Application to breast cancer cell lines"}, [])
    assert good["score"] > vague["score"]
    assert "control_context" in good["reasons"]
    model = relevance(spec, {"title": "Human breast cancer co-culture model", "summary": "Patients and healthy controls motivate this work."}, [])
    assert good["score"] > model["score"]


def test_similar_studies_do_not_take_all_deep_slots():
    summaries = {"GSE1": {"title": "Effects of TEAD4 knockdown on rheumatoid arthritis synovial fibroblasts"},
                 "GSE2": {"title": "Effects of GLI1 knockdown on rheumatoid arthritis synovial fibroblasts"},
                 "GSE3": {"title": "Patient biopsy transcriptome and healthy cohort comparison"}}
    rows = [SimpleNamespace(gse=g, verification_status="summary_screened", first_assess_json=json.dumps({"selection": {"score": score}}))
            for g, score in [("GSE1", 60), ("GSE2", 59), ("GSE3", 58)]]
    assert select_deep_targets(rows, summaries, 2) == ["GSE1", "GSE3"]
    assert select_deep_targets(rows[::-1], summaries, 3) == ["GSE1", "GSE3", "GSE2"]


def test_unused_deep_slots_fill_below_near_peer_margin():
    summaries = {f"GSE{i}": {"title": f"Distinct study {i} transcriptome"} for i in (1, 2, 3)}
    rows = [SimpleNamespace(gse=g, verification_status="summary_screened",
                            first_assess_json=json.dumps({"selection": {"score": score}}))
            for g, score in [("GSE1", 100), ("GSE2", 70), ("GSE3", 60)]]
    assert select_deep_targets(rows, summaries, 3) == ["GSE1", "GSE2", "GSE3"]


def test_scrna_downranks_microbiome_proteomics_and_spatial():
    spec = heuristic_parse("human primary atherosclerosis plaque scRNA-seq with disease vs control")
    host = relevance(spec, {
        "title": "Single-cell RNA-seq of human atherosclerotic plaque biopsies from patients and controls",
        "gdstype": "Expression profiling by high throughput sequencing",
    }, [])
    microbiota = relevance(spec, {
        "title": "Possible association between the microbiota in subgingival and atherosclerotic plaque",
        "gdstype": "Other",
    }, [])
    visium = relevance(spec, {
        "title": "Targeting modulated vascular smooth muscle cells in atherosclerosis [Visium]",
        "gdstype": "Expression profiling by high throughput sequencing",
    }, [])
    assert "off_assay_microbiome" in microbiota["reasons"]
    assert "off_assay_spatial" in visium["reasons"]
    assert host["score"] > microbiota["score"]
    assert host["score"] > visium["score"]
    spec_ad = heuristic_parse("human primary Alzheimer disease brain snRNA-seq")
    snrna = relevance(spec_ad, {
        "title": "Postmortem cortex single-nucleus RNA-seq in Alzheimer’s disease",
        "gdstype": "Expression profiling by high throughput sequencing",
    }, [])
    proteomics = relevance(spec_ad, {
        "title": "Mass spectrometry-based proteomic profiling of human postmortem brain tissues in Alzheimer’s disease",
        "gdstype": "Expression profiling by high throughput sequencing",
    }, [])
    assert "off_assay_proteomics" in proteomics["reasons"]
    assert snrna["score"] > proteomics["score"]
    summaries = {
        "GSEHOST": {
            "title": "Single-cell RNA-seq of human atherosclerotic plaque biopsies from patients and controls",
            "gdstype": "Expression profiling by high throughput sequencing",
        },
        "GSEMICRO": {
            "title": "Possible association between the microbiota in subgingival and atherosclerotic plaque",
            "gdstype": "Other",
        },
    }
    rows = [
        SimpleNamespace(
            gse=gse,
            verification_status="summary_screened",
            first_assess_json=json.dumps({"selection": relevance(spec, summary, [])}),
        )
        for gse, summary in summaries.items()
    ]
    assert select_deep_targets(rows, summaries, 1) == ["GSEHOST"]


def test_legacy_query_order_migration_is_stable():
    db = create_engine("sqlite://")
    with db.begin() as conn:
        Base.metadata.create_all(conn)
        conn.execute(text("ALTER TABLE query_attempts DROP COLUMN query_index"))
        conn.execute(text("ALTER TABLE query_attempts DROP COLUMN candidate_limit"))
        for ident, source in [("a", "planner"), ("z", "user")]:
            conn.execute(text("INSERT INTO query_attempts (id,run_id,query_hash,term,round_no,source,new_unique_gse,retstart,pages_done,query_translation,truncated,status,error_message) VALUES (:id,'r',:id,:id,1,:source,0,0,0,'',0,'pending','')"), {"id": ident, "source": source})
        _migrate_sqlite_columns(conn)
        assert conn.execute(text("SELECT id FROM query_attempts ORDER BY query_index")).scalars().all() == ["z", "a"]
        _migrate_sqlite_columns(conn)
        assert conn.execute(text("SELECT query_index FROM query_attempts ORDER BY query_index")).scalars().all() == [0, 1]
    db.dispose()


@pytest.mark.asyncio
async def test_search_executes_user_first_and_deduplicates_quota(monkeypatch):
    calls = []
    original = MockNCBIClient.esearch

    async def capture(self, term, **kwargs):
        calls.append((term, kwargs))
        return await original(self, term, **kwargs)

    monkeypatch.setattr(MockNCBIClient, "esearch", capture)
    await init_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1:8000") as client:
        project = (await client.post("/api/projects", json={"original_request": "human atherosclerosis scRNA-seq"})).json()
        run = (await client.post(f"/api/projects/{project['id']}/runs", json={"mode": "full", "budget": {"max_unique_gse": 3, "max_queries": 4, "max_deep_verify": 0}})).json()
        await _drain(run["id"], limit=120)
        queries = (await client.get(f"/api/runs/{run['id']}/queries")).json()
        rows = (await client.get(f"/api/runs/{run['id']}/datasets")).json()
    assert queries[0]["source"] == "user"
    assert calls[0][0] == queries[0]["term"]
    assert calls[0][1]["retmax"] == 1
    assert len({term for term, _ in calls}) >= 3
    assert rows["total"] == 3
    assert sum(q["new_unique_gse"] for q in queries) == 3

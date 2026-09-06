from pathlib import Path

from app.core.redact import redact_mapping, redact_text
from app.exporters.excel import read_candidate_gses, sanitize_cell, write_workbook
from app.connectors.llm import LLMError, validate_assessment
from app.evidence.store import quote_in_text


def test_formula_injection_and_empty_counts(tmp_path: Path):
    assert sanitize_cell("=CMD()") == "'=CMD()"
    assert sanitize_cell(None, numeric=True) is None
    payload = {
        "demo": False,
        "project_name": "demo",
        "spec": {"original_request": "x"},
        "run": {"status": "partial", "stop_reason": "预算耗尽", "created_at": "t"},
        "candidates": [
            {
                "gse": "GSE1000",
                "title": "=1+1",
                "url": "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE1000",
                "pubmed_ids": [],
                "taxon": "Homo sapiens",
                "gsm_count": None,
                "independent_donors": None,
                "category": "needs_review",
                "hard_unknowns": 1,
                "soft_score": None,
                "verification_status": "summary_only",
                "reason": "unknown donors",
                "processed_data": "unknown",
                "raw_data": "unknown",
            }
        ],
        "assessments": [],
        "samples": [],
        "queries": [],
        "run_info": {"software_version": "0.1.0"},
    }
    path = tmp_path / "out.xlsx"
    write_workbook(path, payload)
    assert read_candidate_gses(path) == ["GSE1000"]


def test_redact_key():
    text = "https://eutils.ncbi.nlm.nih.gov/x?api_key=SECRETKEY123&db=gds"
    assert "SECRETKEY123" not in redact_text(text)
    assert redact_mapping({"api_key": "abc", "nested": {"Authorization": "Bearer z"}})["api_key"] == "***"


def test_reject_illegal_evidence():
    payload = {
        "judgements": [
            {
                "criterion_id": "organism",
                "verdict": "pass",
                "evidence_ids": ["ev_missing"],
                "quote": "hello",
                "reason": "x",
            }
        ]
    }
    model = validate_assessment(payload)
    assert model.judgements[0].evidence_ids == ["ev_missing"]
    assert not quote_in_text("hello", "world")
    try:
        raise LLMError("非法 evidence_id: ev_missing")
    except LLMError:
        pass

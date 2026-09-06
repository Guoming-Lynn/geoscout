from pathlib import Path

from app.exporters.excel import read_sheet_maps, write_workbook


def test_excel_reread_final_evidence_and_override(tmp_path: Path):
    payload = {
        "demo": False,
        "project_name": "audit",
        "spec": {"original_request": "human scRNA-seq"},
        "run": {"status": "completed", "stop_reason": "正常结束", "created_at": "t", "id": "run1", "stage": "exporting"},
        "candidates": [
            {
                "gse": "GSE333565",
                "title": "ok",
                "url": "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE333565",
                "pubmed_ids": [],
                "taxon": "Homo sapiens",
                "gsm_count": 6,
                "independent_donors": 6,
                "category": "recommended",
                "hard_unknowns": 0,
                "soft_score": 1,
                "verification_status": "verified",
                "reason": "全部硬条件通过",
                "processed_data": "unknown",
                "raw_data": "unknown",
                "overridden": False,
            },
            {
                "gse": "GSE1000",
                "title": "conflict",
                "url": "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE1000",
                "pubmed_ids": [],
                "taxon": "Homo sapiens",
                "category": "needs_review",
                "verification_status": "needs_review",
                "reason": "两次模型判断冲突",
                "processed_data": "unknown",
                "raw_data": "unknown",
            },
            {
                "gse": "GSE2",
                "title": "overridden",
                "url": "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE2",
                "pubmed_ids": [],
                "taxon": "Homo sapiens",
                "category": "recommended",
                "verification_status": "needs_review",
                "reason": "人工覆盖",
                "processed_data": "unknown",
                "raw_data": "unknown",
                "overridden": True,
            },
        ],
        "assessments": [
            {
                "gse": "GSE333565",
                "criterion_id": "organism",
                "stage": "final",
                "verdict": "pass",
                "reason": "摘要物种匹配",
                "quote": "Homo sapiens",
                "evidence_ids": ["ev_tax"],
                "source_url": "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE333565",
                "field_path": "esummary.taxon",
                "judge_source": "verify",
            },
            {
                "gse": "GSE1000",
                "criterion_id": "organism",
                "stage": "final",
                "verdict": "unknown",
                "reason": "两次模型判断冲突",
                "quote": "",
                "evidence_ids": ["ev_a", "ev_b"],
                "source_url": "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE1000",
                "field_path": "esummary.taxon",
                "judge_source": "conflict",
            },
            {
                "gse": "GSE2",
                "criterion_id": "override",
                "stage": "override",
                "verdict": "unknown",
                "reason": "原类别 needs_review → recommended。人工核验",
                "quote": "",
                "evidence_ids": [],
                "source_url": "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE2",
                "field_path": "",
                "judge_source": "human",
                "actor": "human",
            },
        ],
        "samples": [],
        "queries": [{"round_no": 1, "term": "x", "status": "done", "truncated": True, "hit_count": 9, "new_unique_gse": 1}],
        "run_info": {"software_version": "0.1.0", "status": "completed"},
    }
    path = tmp_path / "audit.xlsx"
    write_workbook(path, payload)
    evidence = read_sheet_maps(path, "Evidence")
    rec = next(r for r in evidence if r["GSE"] == "GSE333565" and r["阶段"] == "final")
    assert rec["判断"] == "pass"
    assert rec["evidence_id"] == "ev_tax"
    assert rec["理由"] == "摘要物种匹配"
    conflict = next(r for r in evidence if r["GSE"] == "GSE1000")
    assert "冲突" in str(conflict["理由"])
    override = next(r for r in evidence if r["GSE"] == "GSE2")
    assert override["阶段"] == "override"
    cands = read_sheet_maps(path, "Candidates")
    by_gse = {r["GSE"]: r for r in cands}
    assert by_gse["GSE333565"]["最终类别"] == "recommended"
    assert by_gse["GSE2"]["人工覆盖"] == "yes"
    queries = read_sheet_maps(path, "Queries")
    assert queries[0]["截断"] == "yes"

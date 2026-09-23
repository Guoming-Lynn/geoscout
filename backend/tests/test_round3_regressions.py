"""Regressions from the 2026-09-23 second DeepSeek Flash run."""

from __future__ import annotations

import json
from pathlib import Path

from app.pipeline.assay import mixed_omics_note
from app.pipeline.assessment import check_model_assessment, fit_samples, merge_final
from app.pipeline.donors import infer_group_label
from app.pipeline.engine import _annotate_reason
from app.pipeline.ranking import relevance
from app.pipeline.screening import rule_gate_ids, rule_judgements
from app.pipeline.source import tissue_matches
from app.pipeline.spec_parse import heuristic_parse
from app.schemas.spec import CriterionJudgement

FIXTURE = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "flash_round2_samples.json").read_text(encoding="utf-8")
)
AD = "human primary Alzheimer disease brain RNA-seq with disease and control"
T2D = "human primary type 2 diabetes islet RNA-seq with disease and control"
RA = "human primary rheumatoid arthritis PBMC RNA-seq with disease and control"


def _entry(gse: str) -> tuple[dict, list[dict]]:
    row = FIXTURE[gse]
    return row["summary"], row["samples"]


def _judgement(spec, gse: str, field: str):
    summary, samples = _entry(gse)
    return next(item for item in rule_judgements(spec, summary, samples) if item.criterion_id == field)


def _sample(key: str, value: str) -> dict:
    return {"gsm": "GSM1", "characteristics": [{"key": key, "value": value, "raw": f"{key}: {value}"}]}


def test_disease_and_control_labels_from_real_field_names():
    t2d = heuristic_parse(T2D)
    assert infer_group_label(_sample("disease", "Type 2 diabetic"), spec=t2d) == "case"
    assert infer_group_label(_sample("disease", "Non-diabetic"), spec=t2d) == "control"
    assert infer_group_label(_sample("diabetes status", "T2D"), spec=t2d) == "case"
    assert infer_group_label(_sample("diabetes status", "ND"), spec=t2d) == "control"
    assert infer_group_label(_sample("diabetes status", "IGT"), spec=t2d) is None
    assert infer_group_label(_sample("diabetes status", "T3cD"), spec=t2d) is None
    assert infer_group_label(_sample("diabetes status", "IFG"), spec=t2d) is None
    assert infer_group_label(_sample("condition", "non-diabetic"), spec=t2d) == "control"
    ra = heuristic_parse(RA)
    assert infer_group_label(_sample("sample group", "HCs"), spec=ra) == "control"
    assert infer_group_label(_sample("sample group", "rheumatoid arthritis (RA)"), spec=ra) == "case"
    treated = {
        "gsm": "GSM9",
        "characteristics": [
            {"key": "diagnosis", "value": "Rheumatoid arthritis", "raw": "diagnosis: Rheumatoid arthritis"},
            {"key": "treatment", "value": "methotrexate", "raw": "treatment: methotrexate"},
        ],
    }
    assert infer_group_label(treated, spec=ra) == "case"


def test_round2_rule_judgements_match_real_cohorts():
    t2d = heuristic_parse(T2D)
    ra = heuristic_parse(RA)
    ad = heuristic_parse(AD)
    expectations = {
        "GSE86468": (t2d, {"assay": "pass", "tissue": "pass", "groups": "pass"}, 24),
        "GSE164416": (t2d, {"assay": "pass", "groups": "pass"}, 57),
        "GSE291978": (ra, {"tissue": "pass", "groups": "pass"}, 6),
        "GSE153855": (t2d, {"groups": "pass"}, None),
        "GSE266852": (ra, {"groups": "pass"}, 7),
        "GSE309036": (ad, {"assay": "fail"}, None),
        "GSE163605": (ra, {"groups": "unknown"}, None),
    }
    for gse, (spec, fields, group_count) in expectations.items():
        for field, verdict in fields.items():
            item = _judgement(spec, gse, field)
            assert item.verdict == verdict, gse
            if field == "assay" and verdict == "fail":
                assert item.clue_only is False
        if group_count is not None:
            assert len(_judgement(spec, gse, "groups").qualifying_gsms) == group_count
    summary, samples = _entry("GSE266852")
    groups = next(item for item in rule_judgements(ra, summary, samples) if item.criterion_id == "groups")
    labels = [infer_group_label(sample, spec=ra) for sample in samples if sample["gsm"] in set(groups.qualifying_gsms)]
    assert labels.count("case") == 3
    assert labels.count("control") == 4


def test_ex_vivo_samples_leave_the_baseline_cohort():
    spec = heuristic_parse(RA)
    summary, samples = _entry("GSE189136")
    groups = next(item for item in rule_judgements(spec, summary, samples) if item.criterion_id == "groups")
    assert groups.verdict == "pass"
    assert len(groups.qualifying_gsms) == 4
    kept = {sample["gsm"] for sample in samples if sample["gsm"] in set(groups.qualifying_gsms)}
    for sample in samples:
        raw = " ".join(str(row.get("raw") or "") for row in sample["characteristics"])
        if sample["gsm"] in kept:
            assert "Untreated" in raw
        elif "treatment:" in raw:
            assert "Untreated" not in raw
    evidence = [{"evidence_id": "ev_ok", "field_path": "soft.Series_summary", "text": "PBMC RNA-seq Rheumatoid arthritis Healthy"}]
    raw = {
        "judgements": [
            {
                "criterion_id": "groups",
                "verdict": "pass",
                "evidence_ids": ["ev_ok"],
                "quote": "PBMC",
                "reason": "17 RA versus 2 healthy",
                "qualifying_gsms": [sample["gsm"] for sample in samples],
            }
        ]
    }
    checked = check_model_assessment(spec, raw, evidence, samples=samples, study=summary)
    assert not checked.invalid
    judged = next(item for item in checked.judgements if item.criterion_id == "groups")
    assert set(judged.qualifying_gsms) == kept
    assert "已移除分组对不上的 GSM" in judged.reason


def test_mirna_series_is_gated_before_the_model():
    spec = heuristic_parse(AD)
    summary, samples = _entry("GSE309036")
    assert rule_gate_ids(spec, summary, samples) == ["assay"]
    assert rule_gate_ids(spec, summary, []) == []


def test_homogeneous_cells_fold_inside_the_prompt_budget():
    _summary, samples = _entry("GSE81608")
    spec = heuristic_parse(T2D)
    packed, coverage = fit_samples(samples, spec=spec, budget=40_000)
    assert coverage["represented"] == len(samples)
    assert coverage["complete"] is True
    assert len(packed) < len(samples)
    assert len(packed) <= 20
    folded = [row for row in packed if row.get("member_count", 1) > 1]
    assert folded
    assert coverage["members"][folded[0]["gsm"].upper()]


def test_rule_covers_groups_when_the_model_only_saw_a_subset():
    spec = heuristic_parse(T2D)
    summary, samples = _entry("GSE164416")
    rules = rule_judgements(spec, summary, samples)
    reason = "样本记录未完整纳入模型输入，不能据此推荐。"
    unknown = [
        CriterionJudgement(criterion_id=item.criterion_id, verdict="unknown", reason=reason, judge_source="model")
        for item in rules
        if item.criterion_id in {"assay", "groups"}
    ]
    merged, _conflicts, _review, _invalid = merge_final(spec, rules, type("A", (), {"invalid": False, "incomplete": False, "judgements": unknown})(), type("A", (), {"invalid": False, "incomplete": False, "judgements": unknown})(), samples=samples, study=summary)
    for field in ("assay", "groups"):
        item = next(row for row in merged if row.criterion_id == field)
        assert item.verdict == "pass"
        assert item.judge_source == "rule_full_coverage"


def test_pbmc_uses_cell_type_and_rejects_sorted_fractions():
    _summary, pbmc = _entry("GSE291978")
    assert all(tissue_matches(sample, ["pbmc"]) for sample in pbmc)
    _summary, mixed = _entry("GSE163605")
    matched = [sample for sample in mixed if tissue_matches(sample, ["pbmc"])]
    assert len(matched) == 29
    assert {sample["source_name"] for sample in matched} == {"PBMCs"}
    olfactory = {"source_name": "Olfactory Epithelium", "characteristics": []}
    assert not tissue_matches(olfactory, ["brain"])


def test_proteomics_title_does_not_claim_a_proteomics_sample():
    summary, samples = _entry("GSE317746")
    note = mixed_omics_note(summary, samples)
    assert "proteomics" in note
    assert "GEO 样本" in note
    assert "系列同时包含" not in note


def test_cohort_size_is_written_into_the_reason():
    spec = heuristic_parse(RA)
    summary, samples = _entry("GSE189136")
    rules = rule_judgements(spec, summary, samples)
    groups = next(item for item in rules if item.criterion_id == "groups")

    class _Row:
        independent_donors = None
        biosample_count = 19
        file_listing_checked = False
        matrix_availability = "unknown"

    text = _annotate_reason("全部硬条件通过。", _Row(), summary, samples, spec=spec, merged=rules)
    assert "适用队列：case 2 / control 2 个 GSM。" in text
    assert "每组样本很少" in text
    assert "样本名提示约" in text
    assert groups.verdict == "pass"


def test_small_rna_title_is_ranked_below_rna_seq():
    spec = heuristic_parse(AD)
    rna = relevance(spec, {"title": "Alzheimer cortex RNA-seq", "gdstype": "Expression profiling by high throughput sequencing"}, [])
    small = relevance(
        spec,
        {
            "title": "Alzheimer cortex miRNA-seq",
            "gdstype": "Non-coding RNA profiling by high throughput sequencing",
        },
        [],
    )
    assert "off_assay_small_rna_hint" in small["reasons"]
    assert rna["score"] > small["score"]

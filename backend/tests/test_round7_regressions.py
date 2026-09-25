"""Defects found verifying the seventh DeepSeek Flash run (2026-09-25)."""

from __future__ import annotations

from app.pipeline.assessment import COVERAGE_DEMOTION_REASON, merge_final
from app.pipeline.engine import _mixed_species_note, _title_individual_count
from app.pipeline.source import tissue_matches
from app.pipeline.spec_parse import heuristic_parse
from app.schemas.spec import CriterionJudgement

UC_TEXT = "human primary ulcerative colitis colon RNA-seq with disease and control"
BR_TEXT = "human primary breast cancer single-cell RNA-seq with disease and control"


def _assessment(judgements):
    return type("A", (), {"invalid": False, "incomplete": False, "judgements": judgements})()


def test_truncated_model_pass_does_not_shrink_the_rule_cohort():
    spec = heuristic_parse(UC_TEXT)
    seen = [f"GSM{i}" for i in range(4)]
    everyone = [f"GSM{i}" for i in range(40)]
    # The model saw GSM0-3 and deliberately left GSM3 out of disease.
    model = [
        CriterionJudgement(criterion_id="disease", verdict="pass", reason="m", qualifying_gsms=seen[:3]),
        CriterionJudgement(criterion_id="organism", verdict="pass", reason="m", qualifying_gsms=seen),
        CriterionJudgement(criterion_id="groups", verdict="unknown", reason=COVERAGE_DEMOTION_REASON, qualifying_gsms=seen),
    ]
    rule = CriterionJudgement(
        criterion_id="disease", verdict="pass", reason="r", qualifying_gsms=everyone, support_text="UC", judge_source="rule"
    )
    merged, *_ = merge_final(spec, [rule], _assessment(model), _assessment(model))
    disease = next(item for item in merged if item.criterion_id == "disease")
    assert "GSM3" not in disease.qualifying_gsms
    assert set(disease.qualifying_gsms) == set(seen[:3]) | set(everyone[4:])


def test_untruncated_model_pass_keeps_its_own_list():
    spec = heuristic_parse(UC_TEXT)
    model = [CriterionJudgement(criterion_id="disease", verdict="pass", reason="m", qualifying_gsms=["GSM1"])]
    rule = CriterionJudgement(
        criterion_id="disease", verdict="pass", reason="r", qualifying_gsms=["GSM1", "GSM2"], support_text="UC"
    )
    merged, *_ = merge_final(spec, [rule], _assessment(model), _assessment(model))
    disease = next(item for item in merged if item.criterion_id == "disease")
    assert disease.qualifying_gsms == ["GSM1"]


def test_colon_request_excludes_ileum():
    spec = heuristic_parse(UC_TEXT)
    assert spec.tissues == ["colon"]
    rectum = {"gsm": "GSM1", "source_name": "Biopsy", "characteristics": [{"key": "regionre", "value": "Rectum"}]}
    ileum = {"gsm": "GSM2", "source_name": "Biopsy", "characteristics": [{"key": "regionre", "value": "Ileum"}]}
    assert tissue_matches(rectum, spec.tissues)
    assert not tissue_matches(ileum, spec.tissues)
    assert heuristic_parse("human Crohn disease intestinal biopsy RNA-seq").tissues == ["intestine"]


def test_mixed_species_is_named():
    spec = heuristic_parse(BR_TEXT)
    samples = [{"gsm": "GSM1", "organism": "Homo sapiens"}, {"gsm": "GSM2", "organism": "Rattus norvegicus"}]
    note = _mixed_species_note(samples, spec)
    assert "Rattus norvegicus 1" in note and "1 个 GSM" in note
    assert _mixed_species_note(samples[:1], spec) == ""


def test_facs_markers_are_not_individuals():
    titles = [
        "Dataset 1: Patient #379-IDC-Myoepithelium fraction (CD10+EpCAM+CD45-)",
        "Dataset 1: Patient #379-IDC-Immune fraction (CD45+ EpCAM- CD10-)",
        "Dataset 1: Patient #402-IDC-Immune fraction (CD45+ EpCAM- CD10-)",
        "Dataset 1: Patient #402-IDC-Stroma fraction (CD10- EpCAM- CD45-)",
        "Dataset 1: Patient #410-DCIS-Stroma fraction (CD10- EpCAM- CD45-)",
        "Dataset 1: Patient #410-DCIS-Immune fraction (CD45+ EpCAM- CD10-)",
    ]
    assert _title_individual_count([{"title": t} for t in titles]) is None
    treated = [{"title": f"Patient {i} anti-OX40"} for i in range(4)] + [{"title": f"Patient {i} anti-PDL1"} for i in range(4)]
    assert _title_individual_count(treated) is None
    donors = [{"title": f"P{i}_{kind}"} for i in range(1, 4) for kind in ("tumor", "normal")]
    assert _title_individual_count(donors) == 3

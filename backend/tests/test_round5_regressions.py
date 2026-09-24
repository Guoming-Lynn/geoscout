"""Defects found in the fifth DeepSeek Flash run (2026-09-24)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from app.pipeline.assessment import CheckedAssessment, merge_final
from app.pipeline.donors import infer_group_label, parse_sample_traits
from app.pipeline.engine import _activity_mix_note, _annotate_reason, _sorted_fraction_note
from app.pipeline.ranking import walk_deep_slots
from app.pipeline.screening import rule_gate_ids, rule_judgements
from app.pipeline.source import sample_tissue_conflicts, sorted_fraction, source_kind, tissue_matches
from app.pipeline.spec_parse import heuristic_parse
from app.schemas.spec import CriterionJudgement

FIXTURES = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "flash_round5_samples.json").read_text(encoding="utf-8")
)
UC_TEXT = "human primary ulcerative colitis colon RNA-seq with disease and control"
BR_TEXT = "human primary breast cancer single-cell RNA-seq with disease and control"
AD_TEXT = "human primary Alzheimer disease brain RNA-seq with disease and control"
IBD_TEXT = "human primary inflammatory bowel disease colon RNA-seq with disease and control"


def _entry(gse: str) -> tuple[dict, list[dict]]:
    row = FIXTURES[gse]
    return row["summary"], row["samples"]


def _counts(spec, samples: list[dict]) -> Counter:
    return Counter(infer_group_label(sample, spec=spec) for sample in samples)


def test_primary_parse_accepts_colon_and_breast():
    assert heuristic_parse(UC_TEXT).sample_source == "primary"
    assert heuristic_parse(BR_TEXT).sample_source == "primary"
    assert heuristic_parse(AD_TEXT).sample_source == "primary"
    assert heuristic_parse("human breast cancer cell line RNA-seq").sample_source == "any"
    assert heuristic_parse("human colon cancer organoid RNA-seq").sample_source == "any"
    assert heuristic_parse("primary cells cultured from patients, not patient tissue").sample_source != "primary"


def test_named_organ_is_primary_and_models_stay_models():
    uc = heuristic_parse(UC_TEXT)
    for gse in ("GSE334803", "GSE224758", "GSE222070"):
        _, samples = _entry(gse)
        assert {source_kind(sample) for sample in samples} == {"primary"}
    _, lung = _entry("GSE313152")
    assert all(source_kind(sample) == "primary" for sample in lung)
    _, organoid = _entry("GSE298343")
    assert all(source_kind(sample) == "organoid" for sample in organoid)
    _, pdx = _entry("GSE309616")
    assert all(source_kind(sample) == "xenograft" for sample in pdx)
    _, chip = _entry("GSE277964")
    assert all(source_kind(sample) != "primary" for sample in chip)
    _, colonoids = _entry("GSE276170")
    assert all(source_kind(sample) == "organoid" for sample in colonoids)
    assert source_kind({"gsm": "GSM1", "source_name": "Colon chip epithelium", "characteristics": []}) == "organoid"
    assert source_kind({
        "gsm": "GSM1",
        "source_name": "biopsy",
        "characteristics": [{"key": "p53 status", "value": "mutant"}],
    }) != "organoid"


def test_model_sources_are_gated_for_primary_requests():
    uc = heuristic_parse(UC_TEXT)
    br = heuristic_parse(BR_TEXT)
    for gse in ("GSE252950", "GSE338456", "GSE309616", "GSE303201"):
        summary, samples = _entry(gse)
        assert "sample_source" in rule_gate_ids(br, summary, samples)
    summary, samples = _entry("GSE298343")
    assert "sample_source" in rule_gate_ids(br, summary, samples)
    for gse in ("GSE102746", "GSE276170"):
        summary, samples = _entry(gse)
        assert "sample_source" in rule_gate_ids(uc, summary, samples)
    summary, samples = _entry("GSE271307")
    assert "sample_source" not in rule_gate_ids(br, summary, samples)


def test_ibd_abbreviations_split_case_and_other_disease():
    uc = heuristic_parse(UC_TEXT)
    ibd = heuristic_parse(IBD_TEXT)
    assert _counts(uc, _entry("GSE235236")[1])["case"] == 26
    assert _counts(uc, _entry("GSE235236")[1])["control"] == 8
    assert _counts(uc, _entry("GSE222070")[1])["case"] == 17
    assert _counts(uc, _entry("GSE222070")[1])["control"] == 10
    assert _counts(uc, _entry("GSE266325")[1])["case"] == 5
    assert _counts(uc, _entry("GSE266325")[1])["control"] == 9
    assert _counts(uc, _entry("GSE123141")[1]) == Counter({"case": 10, "control": 9, None: 9})
    assert _counts(ibd, _entry("GSE123141")[1])["case"] == 19
    assert infer_group_label(
        {"gsm": "GSM1", "characteristics": [{"key": "cell type", "value": "CD4+ T cells"}]},
        spec=uc,
    ) is None


def test_strain_is_ex_vivo_and_no_strain_stays_baseline():
    uc = heuristic_parse(UC_TEXT)
    _, samples = _entry("GSE277964")
    strain = [sample for sample in samples if any(
        str(row.get("value") or "").casefold() == "strain"
        for row in sample.get("characteristics") or []
        if isinstance(row, dict) and str(row.get("key") or "").casefold() == "stimulus"
    )]
    assert strain
    assert all(parse_sample_traits(sample, spec=uc).treatment == "ex_vivo" for sample in strain)
    assert all(infer_group_label(sample, spec=uc) is None for sample in strain)
    baseline = _counts(uc, samples)
    assert baseline["case"] == 12
    assert baseline["control"] == 14
    assert infer_group_label(
        {"gsm": "GSM1", "characteristics": [{"key": "treatment", "value": "methotrexate"}]},
        spec=uc,
    ) is None
    assert parse_sample_traits(
        {"gsm": "GSM1", "characteristics": [{"key": "treatment", "value": "healthy"}]},
        spec=uc,
    ).treatment is None


def test_rectum_and_region_fields_match_intestine_not_ileum_as_colon():
    uc = heuristic_parse(UC_TEXT)
    _, rectal = _entry("GSE266325")
    assert all(tissue_matches(sample, uc.tissues) for sample in rectal)
    _, big = _entry("GSE193677")
    matched = [sample for sample in big if tissue_matches(sample, uc.tissues)]
    assert matched
    ileum = [
        sample for sample in big
        if any(str(row.get("value") or "") == "Ileum" for row in sample.get("characteristics") or [] if isinstance(row, dict))
    ]
    assert ileum
    assert all(tissue_matches(sample, ["intestine"]) for sample in ileum)
    assert not any(tissue_matches(sample, ["colon"]) for sample in ileum)


def test_pbmc_and_lung_do_not_match_breast():
    br = heuristic_parse(BR_TEXT)
    for gse in ("GSE300475", "GSE313152"):
        summary, samples = _entry(gse)
        assert not any(tissue_matches(sample, br.tissues) for sample in samples)
        assert "tissue" in rule_gate_ids(br, summary, samples)
    kept = {
        "gsm": "GSM1",
        "source_name": "breast",
        "characteristics": [{"key": "tissue", "value": "breast tumor, lymph node negative"}],
    }
    assert tissue_matches(kept, br.tissues)
    assert not sample_tissue_conflicts(kept, br.tissues)


def test_quote_demotion_keeps_sample_level_disease_pass():
    uc = heuristic_parse(UC_TEXT)
    summary, samples = _entry("GSE224758")
    rules = rule_judgements(uc, summary, samples)
    disease = next(item for item in rules if item.criterion_id == "disease")
    assert disease.verdict == "pass" and disease.qualifying_gsms
    demoted = CriterionJudgement(
        criterion_id="disease",
        verdict="unknown",
        reason="引句无法在证据 ev_x 原文中核对，改为 unknown。",
        judge_source="model",
    )
    passed = CriterionJudgement(criterion_id="disease", verdict="pass", reason="ok", judge_source="model", qualifying_gsms=["GSM1"])
    others = [
        CriterionJudgement(criterion_id=item.criterion_id, verdict="pass", reason="ok", judge_source="model")
        for item in rules
        if item.criterion_id != "disease"
    ]
    merged, _, _, _ = merge_final(
        uc,
        rules,
        CheckedAssessment(judgements=[demoted, *others]),
        CheckedAssessment(judgements=[passed, *others]),
        samples=samples,
        study=summary,
    )
    final = next(item for item in merged if item.criterion_id == "disease")
    assert final.verdict == "pass"
    keyword_only = disease.model_copy(update={"qualifying_gsms": [], "reason": "文本出现相关词。"})
    rules_keyword = [keyword_only if item.criterion_id == "disease" else item for item in rules]
    merged_keyword, _, _, _ = merge_final(
        uc,
        rules_keyword,
        CheckedAssessment(judgements=[demoted, *others]),
        CheckedAssessment(judgements=[passed, *others]),
        samples=samples,
        study=summary,
    )
    assert next(item for item in merged_keyword if item.criterion_id == "disease").verdict != "pass"


def test_sorted_macrophages_are_noted_and_biopsies_are_not():
    uc = heuristic_parse(UC_TEXT)
    _, macrophages = _entry("GSE123141")
    assert sorted_fraction(macrophages[0])
    assert "分选的" in _sorted_fraction_note(macrophages, uc)
    _, biopsies = _entry("GSE334803")
    assert _sorted_fraction_note(biopsies, uc) == ""


def test_active_and_inactive_cases_are_noted():
    labels = {"GSM1": "case", "GSM2": "case"}
    samples = [
        {"gsm": "GSM1", "characteristics": [{"key": "diagnosis", "value": "Active UC"}]},
        {"gsm": "GSM2", "characteristics": [{"key": "diagnosis", "value": "Inactive UC"}]},
    ]
    assert "活动期" in _activity_mix_note(samples, labels)


def test_deep_backfill_stops_at_the_model_cap():
    gated = [True] * 12 + [False] * 8
    assert walk_deep_slots(gated, 10) == (8, 20)
    assert walk_deep_slots([True] * 5 + [False] * 15, 10) == (10, 15)


def test_cohort_reason_uses_real_samples():
    uc = heuristic_parse(UC_TEXT)
    summary, samples = _entry("GSE123141")

    class _Row:
        independent_donors = None
        biosample_count = len(samples)
        file_listing_checked = False
        matrix_availability = "unknown"

    rules = rule_judgements(uc, summary, samples)
    text = _annotate_reason("ok", _Row(), summary, samples, spec=uc, merged=rules)
    assert "分选的" in text
    assert "intestinal macrophages" in text

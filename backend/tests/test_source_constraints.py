import pytest

from app.pipeline.assessment import _restrict_to_common_subset
from app.pipeline.screening import classify, rule_judgements
from app.pipeline.source import source_kind
from app.pipeline.spec_parse import heuristic_parse, merge_model_parse, _fill_criteria
from app.schemas.spec import CriterionJudgement, ResearchSpec, RunCreate


def test_source_defaults_do_not_reinterpret_legacy_human_topics():
    assert heuristic_parse("human tissue RNA-seq").sample_source == "any"
    assert heuristic_parse("primary patient tissue RNA-seq").sample_source == "primary"
    assert ResearchSpec().tissue_required is False
    assert heuristic_parse("exclude primary patient tissue").sample_source == "any"
    assert heuristic_parse("human patient-derived RNA-seq").sample_source == "any"
    assert heuristic_parse("primary progressive multiple sclerosis RNA-seq").sample_source == "any"


@pytest.mark.parametrize("text", [
    "human primary atherosclerosis plaque scRNA-seq with disease vs control",
    "human primary type 2 diabetes pancreatic islet RNA-seq",
    "human primary Alzheimer disease brain snRNA-seq",
    "human Alzheimer disease primary brain RNA-seq",
])
def test_primary_before_named_tissue_is_sample_source(text):
    spec = heuristic_parse(text)
    assert spec.sample_source == "primary"
    assert any(c.criterion_id == "sample_source" and c.priority == "hard" for c in spec.inclusion_criteria)


def test_model_parse_may_set_primary_only_when_request_names_material():
    named = ResearchSpec(original_request="human primary atherosclerosis plaque scRNA-seq")
    assert named.sample_source == "any"
    assert merge_model_parse(named, {"sample_source": "primary"}).sample_source == "primary"
    derived = ResearchSpec(original_request="human patient-derived RNA-seq")
    assert merge_model_parse(derived, {"sample_source": "primary"}).sample_source == "any"


@pytest.mark.parametrize("text,expected", [("human patient-derived", None), ("patient-derived organoid", "organoid"), ("iPSC astrocytes", "cell_line"), ("PDX tumor", "xenograft"), ("blood draw", "primary"), ("cultured primary tissue", None), ("PBMC", "primary"), ("Pancreatic islets", "primary"), ("dentate gyrus", "primary")])
def test_provenance_requires_explicit_sample_evidence(text, expected):
    assert source_kind({"source_name": text}) == expected


def test_hek293t_protocol_serum_is_not_primary():
    sample = {
        "gsm": "GSM1",
        "source_name": "HEK293T",
        "protocol": "Cells were maintained in DMEM supplemented with 10% fetal bovine serum.",
    }
    assert source_kind(sample) == "cell_line"


def test_pbmc_negation_is_not_cell_line():
    sample = {
        "gsm": "GSM1",
        "source_name": "PBMC",
        "protocol": "No cell lines were used.",
    }
    assert source_kind(sample) == "primary"


def test_cultured_pbmc_protocol_is_not_primary():
    sample = {
        "gsm": "GSM1",
        "source_name": "PBMC",
        "protocol": "Cells were cultured in vitro for 14 days.",
    }
    assert source_kind(sample) is None


def test_contradictory_line_and_primary_stay_unknown():
    assert source_kind({"source_name": "PBMC from HEK293T"}) is None


def test_hek293t_cannot_pass_primary_rule_or_recommend():
    spec = ResearchSpec(sample_source="primary", organisms=["Homo sapiens"])
    _fill_criteria(spec)
    sample = {
        "gsm": "GSM1",
        "source_name": "HEK293T",
        "organism": "Homo sapiens",
        "protocol": "Cells were maintained in DMEM supplemented with 10% fetal bovine serum.",
    }
    j = CriterionJudgement(criterion_id="sample_source", verdict="pass", qualifying_gsms=["GSM1"])
    restricted = _restrict_to_common_subset(spec, [j], [sample])
    assert restricted[0].verdict == "unknown"
    from app.pipeline.screening import classify
    cat, _ = classify(spec, restricted, verified=True, conflict=False, model_invalid=False)
    assert cat != "recommended"


def test_cultured_pbmc_cannot_pass_primary_rule():
    spec = ResearchSpec(sample_source="primary", organisms=["Homo sapiens"])
    _fill_criteria(spec)
    sample = {
        "gsm": "GSM1",
        "source_name": "PBMC",
        "organism": "Homo sapiens",
        "protocol": "Cells were cultured in vitro for 14 days.",
    }
    j = CriterionJudgement(criterion_id="sample_source", verdict="pass", qualifying_gsms=["GSM1"])
    restricted = _restrict_to_common_subset(spec, [j], [sample])
    assert restricted[0].verdict == "unknown"
    from app.pipeline.screening import classify
    cat, _ = classify(spec, restricted, verified=True, conflict=False, model_invalid=False)
    assert cat != "recommended"


def test_ivt_and_library_protocols_do_not_override_primary_pbmc():
    ivt = {
        "gsm": "GSM1",
        "source_name": "PBMC",
        "protocol": "RNA was amplified by in vitro transcription",
    }
    library = {
        "gsm": "GSM2",
        "source_name": "PBMC",
        "protocol": "Libraries were constructed by in vitro transcription of amplified RNA.",
    }
    typed = {
        "gsm": "GSM3",
        "source_name": "PBMC",
        "protocol": "RNA was amplified by in vitro transcription",
        "protocol_fields": {
            "extract_protocol": "RNA was amplified by in vitro transcription",
        },
    }
    assert source_kind(ivt) == "primary"
    assert source_kind(library) == "primary"
    assert source_kind(typed) == "primary"


def test_growth_culture_is_not_hidden_by_extract_ivt():
    sample = {
        "gsm": "GSM1",
        "source_name": "PBMC",
        "protocol": "Cells were cultured in vitro for 14 days. RNA was amplified by in vitro transcription.",
        "protocol_fields": {
            "growth_protocol": "Cells were cultured in vitro for 14 days.",
            "extract_protocol": "RNA was amplified by in vitro transcription",
        },
    }
    assert source_kind(sample) is None


def test_ivt_extract_cannot_downgrade_primary_hard_rule():
    spec = ResearchSpec(sample_source="primary", organisms=["Homo sapiens"])
    _fill_criteria(spec)
    sample = {
        "gsm": "GSM1",
        "source_name": "PBMC",
        "organism": "Homo sapiens",
        "protocol": "RNA was amplified by in vitro transcription",
        "protocol_fields": {"extract_protocol": "RNA was amplified by in vitro transcription"},
    }
    j = CriterionJudgement(criterion_id="sample_source", verdict="pass", qualifying_gsms=["GSM1"])
    assert _restrict_to_common_subset(spec, [j], [sample])[0].verdict == "pass"


@pytest.mark.parametrize("samples,gsms,expected", [([], [], "unknown"), ([{"gsm": "GSM1", "source_name": "patient-derived organoid"}], ["GSM1"], "unknown"), ([{"gsm": "GSM1", "source_name": "blood draw"}], ["GSM1"], "pass")])
def test_source_pass_cannot_bypass_sample_gate(samples, gsms, expected):
    spec = ResearchSpec(sample_source="primary")
    _fill_criteria(spec)
    j = CriterionJudgement(criterion_id="sample_source", verdict="pass", qualifying_gsms=gsms)
    assert _restrict_to_common_subset(spec, [j], samples)[0].verdict == expected


def test_named_intestinal_tissue_is_hard_and_pbmc_cannot_pass_from_abstract():
    spec = heuristic_parse("人炎症性肠病肠组织 ATAC-seq")
    assert "intestine" in spec.tissues
    assert spec.tissue_required is True
    assert next(c.priority for c in spec.inclusion_criteria if c.criterion_id == "tissue") == "hard"
    samples = [{
        "gsm": "GSM1",
        "organism": "Homo sapiens",
        "source_name": "PBMC",
        "library_strategy": "ATAC-seq",
        "characteristics": [{"key": "tissue", "value": "blood", "raw": "tissue: blood"}],
    }]
    judgements = rule_judgements(
        spec,
        {
            "title": "PBMC ATAC-seq in IBD",
            "summary": "Intestinal inflammation in IBD; PBMCs were profiled.",
            "taxon": "Homo sapiens",
            "gdstype": "Genome binding/occupancy profiling by high throughput sequencing",
        },
        samples,
    )
    tissue = next(j for j in judgements if j.criterion_id == "tissue")
    assert tissue.verdict == "fail"
    cat, _ = classify(spec, judgements, verified=True, conflict=False, model_invalid=False)
    assert cat != "recommended"
    colon = rule_judgements(
        spec,
        {"title": "Colon ATAC-seq in IBD", "summary": "Intestinal biopsies.", "taxon": "Homo sapiens"},
        [{"gsm": "GSM2", "organism": "Homo sapiens", "source_name": "colon biopsy",
          "characteristics": [{"key": "tissue", "value": "colon", "raw": "tissue: colon"}]}],
    )
    assert next(j for j in colon if j.criterion_id == "tissue").verdict == "pass"


def test_model_invented_tissue_is_not_required():
    spec = merge_model_parse(ResearchSpec(original_request="human IBD ATAC-seq"), {"tissues": ["liver"]})
    assert spec.tissues == ["liver"]
    assert spec.tissue_required is False
    spec = ResearchSpec(tissues=["brain"], tissue_required=True)
    _fill_criteria(spec)
    j = CriterionJudgement(criterion_id="tissue", verdict="pass", qualifying_gsms=["GSM1"])
    assert _restrict_to_common_subset(spec, [j], [{"gsm": "GSM1", "title": "brain cancer", "source_name": "blood"}])[0].verdict == "unknown"


def test_brain_regions_match_brain_tissue():
    spec = ResearchSpec(tissues=["brain"], tissue_required=True)
    _fill_criteria(spec)
    for source in ["Dentate gyrus", "hippocampus", "frontal cortex", "pons"]:
        j = CriterionJudgement(criterion_id="tissue", verdict="pass", qualifying_gsms=["GSM1"])
        assert _restrict_to_common_subset(spec, [j], [{"gsm": "GSM1", "source_name": source}])[0].verdict == "pass"


def test_deep_limit_bounds():
    assert RunCreate(tier="low", deep_limit=10).deep_limit == 10
    for value in [-1, 1501]:
        with pytest.raises(ValueError):
            RunCreate(deep_limit=value)

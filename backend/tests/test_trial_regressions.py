import pytest

from app.pipeline.assessment import check_model_assessment, merge_final
from app.pipeline.screening import rule_judgements
from app.pipeline.spec_parse import heuristic_parse


@pytest.mark.parametrize("types", [
    "Expression profiling by high throughput sequencing; Expression profiling by array",
    ["Expression profiling by array", "Expression profiling by high throughput sequencing"],
])
def test_mixed_array_rnaseq_is_not_excluded(types):
    spec = heuristic_parse("human type 2 diabetes RNA-seq")
    assay = next(j for j in rule_judgements(spec, {"gdstype": types}) if j.criterion_id == "assay")
    assert assay.verdict == "unknown"
    assert assay.clue_only


@pytest.mark.parametrize("field", ["organism", "disease", "assay"])
def test_two_models_cannot_exclude_mixed_study(field):
    spec = heuristic_parse("human rheumatoid arthritis RNA-seq")
    samples = [
        {"gsm": "GSM1", "organism": "Homo sapiens", "library_strategy": "RNA-Seq", "title": "RA patient synovia"},
        {"gsm": "GSM2", "organism": "Mus musculus", "library_strategy": "RNA-Seq"},
    ]
    study = {"taxon": "Homo sapiens; Mus musculus"}
    evidence = [{"evidence_id": "ev", "field_path": "soft.sample.GSM2.record", "text": "Mus musculus"}]
    raw = {"judgements": [dict(criterion_id=c.criterion_id, verdict="fail" if c.field == field else "unknown",
                              reason="not exclusively human RA", evidence_ids=["ev"] if c.field == field else [],
                              quote="Mus musculus" if c.field == field else "") for c in spec.inclusion_criteria]}
    first = check_model_assessment(spec, raw, evidence, samples, study)
    second = check_model_assessment(spec, raw, evidence, samples, study)
    final, _, _, _ = merge_final(spec, rule_judgements(spec, study, samples), first, second, samples, study)
    assert next(j for j in final if j.criterion_id == field).verdict == "unknown"


def test_pure_wrong_species_still_excluded():
    spec = heuristic_parse("human breast cancer RNA-seq")
    samples = [{"gsm": "GSM1", "organism": "Mus musculus"}]
    evidence = [{"evidence_id": "ev", "text": "Mus musculus"}]
    raw = {"judgements": [{"criterion_id": "organism", "verdict": "fail", "evidence_ids": ["ev"], "quote": "Mus musculus"}]}
    result = check_model_assessment(spec, raw, evidence, samples, {"taxon": "Mus musculus"})
    assert result.judgements[0].verdict == "fail"


def test_incomplete_samples_cannot_prove_whole_study_failure():
    spec = heuristic_parse("human breast cancer RNA-seq")
    raw = {"judgements": [{"criterion_id": "organism", "verdict": "fail", "evidence_ids": ["ev"], "quote": "Mus musculus"}]}
    result = check_model_assessment(spec, raw, [{"evidence_id": "ev", "text": "Mus musculus"}],
                                    [{"gsm": "GSM1", "organism": "Mus musculus"}], {}, {"complete": False})
    assert result.judgements[0].verdict == "unknown"


def test_genome_tiling_methylation_array_is_not_rnaseq():
    spec = heuristic_parse("human Alzheimer disease RNA-seq")
    assay = next(j for j in rule_judgements(spec, {"gdstype": "Methylation profiling by genome tiling array"}) if j.criterion_id == "assay")
    assert assay.verdict == "fail"

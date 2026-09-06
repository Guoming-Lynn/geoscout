from app.pipeline.screening import classify, rule_judgements
from app.pipeline.spec_parse import heuristic_parse
from app.schemas.spec import CriterionJudgement


def test_species_mismatch_excludes():
    spec = heuristic_parse("human atherosclerosis scRNA-seq")
    judgements = rule_judgements(spec, {"taxon": "Mus musculus", "title": "mouse", "summary": "", "gdstype": ""}, [])
    org = next(j for j in judgements if j.criterion_id == "organism")
    assert org.verdict == "fail"
    cat, _ = classify(spec, judgements, verified=True, conflict=False, model_invalid=False)
    assert cat == "excluded"


def test_missing_clinical_is_unknown_not_fail():
    spec = heuristic_parse("人类单细胞，最好包含年龄和性别")
    judgements = rule_judgements(spec, {"taxon": "Homo sapiens", "title": "scrna", "summary": "single-cell RNA sequencing", "gdstype": "Expression profiling by high throughput sequencing"}, [])
    age = next(j for j in judgements if j.criterion_id == "meta_age")
    assert age.verdict == "unknown"


def test_conflict_goes_to_review():
    spec = heuristic_parse("human scRNA-seq")
    judgements = [
        CriterionJudgement(criterion_id="organism", verdict="pass"),
        CriterionJudgement(criterion_id="assay", verdict="pass"),
    ]
    cat, _ = classify(spec, judgements, verified=True, conflict=True, model_invalid=False)
    assert cat == "needs_review"


def test_groups_fail_without_depth_is_review_not_exclude():
    spec = heuristic_parse("human atherosclerosis scRNA-seq lesion vs control")
    judgements = [
        CriterionJudgement(criterion_id="organism", verdict="pass"),
        CriterionJudgement(criterion_id="assay", verdict="unknown"),
        CriterionJudgement(criterion_id="groups", verdict="fail", reason="摘要没有 lesion"),
    ]
    cat, reason = classify(
        spec,
        judgements,
        verified=False,
        conflict=False,
        model_invalid=False,
        depth_complete=False,
        review_complete=False,
    )
    assert cat == "needs_review"
    assert "样本级" in reason


def test_array_vs_scrna_excludes():
    spec = heuristic_parse("human atherosclerosis scRNA-seq")
    judgements = rule_judgements(
        spec,
        {
            "taxon": "Homo sapiens",
            "title": "Osteosarcoma array",
            "summary": "CEL files",
            "gdstype": "Expression profiling by array",
        },
        [],
    )
    assay = next(j for j in judgements if j.criterion_id == "assay")
    assert assay.verdict == "fail"
    cat, _ = classify(spec, judgements, verified=True, conflict=False, model_invalid=False)
    assert cat == "excluded"


def test_array_vs_scrna_excludes_when_value_is_string():
    spec = heuristic_parse("human atherosclerosis scRNA-seq")
    assay_c = next(c for c in spec.inclusion_criteria if c.criterion_id == "assay")
    assay_c.value = "scrna_seq"
    judgements = rule_judgements(
        spec,
        {
            "taxon": "Homo sapiens",
            "title": "Osteosarcoma array",
            "summary": "CEL files",
            "gdstype": "Expression profiling by array",
        },
        [],
    )
    assay = next(j for j in judgements if j.criterion_id == "assay")
    assert assay.verdict == "fail"


def test_array_gdstype_from_type_list():
    spec = heuristic_parse("human scRNA-seq")
    judgements = rule_judgements(
        spec,
        {
            "taxon": "Homo sapiens",
            "title": "array",
            "summary": "",
            "type": ["Expression profiling by array"],
        },
        [],
    )
    assay = next(j for j in judgements if j.criterion_id == "assay")
    assert assay.verdict == "fail"


def test_model_invalid_not_mixed_with_missing_science():
    spec = heuristic_parse("human scRNA-seq")
    judgements = [
        CriterionJudgement(criterion_id="organism", verdict="unknown"),
        CriterionJudgement(criterion_id="assay", verdict="unknown"),
    ]
    cat, reason = classify(spec, judgements, verified=False, conflict=False, model_invalid=True)
    assert cat == "needs_review"
    assert reason.startswith("复核失败")


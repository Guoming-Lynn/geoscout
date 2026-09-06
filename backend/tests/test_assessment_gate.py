from app.pipeline.assessment import check_model_assessment, judge_user_payload, merge_final
from app.pipeline.screening import classify
from app.pipeline.spec_parse import heuristic_parse
from app.schemas.spec import CriterionJudgement, ResearchSpec


def _spec() -> ResearchSpec:
    return heuristic_parse("human atherosclerosis scRNA-seq")


def _spec_with_groups() -> ResearchSpec:
    return heuristic_parse("human atherosclerosis scRNA-seq lesion vs control")


EV = [{"evidence_id": "ev_ok", "text": "taxon: Homo sapiens single-cell RNA sequencing atherosclerosis"}]


def test_empty_evidence_pass_is_invalid():
    spec = _spec()
    raw = {
        "judgements": [
            {"criterion_id": "organism", "verdict": "pass", "evidence_ids": [], "quote": "", "reason": "guess"},
            {"criterion_id": "assay", "verdict": "unknown", "evidence_ids": [], "quote": "", "reason": "x"},
            {"criterion_id": "disease", "verdict": "unknown", "evidence_ids": [], "quote": "", "reason": "x"},
        ]
    }
    checked = check_model_assessment(spec, raw, EV)
    assert checked.invalid
    cat, _ = classify(spec, checked.judgements, verified=True, conflict=False, model_invalid=True)
    assert cat != "recommended"


def test_invented_evidence_id_rejected():
    spec = _spec()
    raw = {
        "judgements": [
            {
                "criterion_id": "organism",
                "verdict": "pass",
                "evidence_ids": ["ev_fake"],
                "quote": "Homo sapiens",
                "reason": "x",
            }
        ]
    }
    checked = check_model_assessment(spec, raw, EV)
    assert checked.invalid


def test_quote_must_match_corresponding_evidence_only():
    spec = _spec()
    evidence = [
        {"evidence_id": "ev1", "text": "Homo sapiens artery"},
        {"evidence_id": "ev2", "text": "unrelated platform GPL96"},
    ]
    raw = {
        "judgements": [
            {
                "criterion_id": "organism",
                "verdict": "pass",
                "evidence_ids": ["ev1", "ev2"],
                "quote": "Homo sapiens",
                "quotes": ["Homo sapiens"],
                "reason": "x",
            },
            {"criterion_id": "assay", "verdict": "unknown", "evidence_ids": [], "reason": "x"},
            {"criterion_id": "disease", "verdict": "unknown", "evidence_ids": [], "reason": "x"},
        ]
    }
    checked = check_model_assessment(spec, raw, evidence)
    assert not checked.invalid
    raw_bad = {
        "judgements": [
            {
                "criterion_id": "organism",
                "verdict": "pass",
                "evidence_ids": ["ev2"],
                "quote": "Homo sapiens",
                "reason": "x",
            }
        ]
    }
    bad = check_model_assessment(spec, raw_bad, evidence)
    assert not bad.invalid
    organism = next(j for j in bad.judgements if j.criterion_id == "organism")
    assert organism.verdict == "unknown"


def test_unknown_and_duplicate_ids_invalid():
    spec = _spec()
    raw = {
        "judgements": [
            {"criterion_id": "not_a_field", "verdict": "pass", "evidence_ids": ["ev_ok"], "quote": "Homo sapiens", "reason": "x"},
            {"criterion_id": "organism", "verdict": "pass", "evidence_ids": ["ev_ok"], "quote": "Homo sapiens", "reason": "x"},
            {"criterion_id": "organism", "verdict": "fail", "evidence_ids": ["ev_ok"], "quote": "Homo sapiens", "reason": "x"},
        ]
    }
    checked = check_model_assessment(spec, raw, EV)
    assert checked.invalid
    assert checked.unknown_ids or checked.duplicate_ids


def test_missing_hard_criterion_cannot_recommend():
    spec = _spec()
    raw = {
        "judgements": [
            {"criterion_id": "organism", "verdict": "pass", "evidence_ids": ["ev_ok"], "quote": "Homo sapiens", "reason": "ok"},
        ]
    }
    checked = check_model_assessment(spec, raw, EV)
    assert checked.incomplete
    assert "assay" in checked.missing_ids or any(j.criterion_id == "assay" and j.verdict == "unknown" for j in checked.judgements)
    cat, _ = classify(
        spec,
        checked.judgements,
        verified=True,
        conflict=False,
        model_invalid=False,
        depth_complete=True,
        review_complete=False,
    )
    assert cat == "needs_review"


def test_conflict_cannot_recommend():
    spec = _spec()
    rules = [
        CriterionJudgement(criterion_id="organism", verdict="unknown", reason="r", judge_source="rule"),
        CriterionJudgement(criterion_id="assay", verdict="unknown", reason="r", judge_source="rule"),
        CriterionJudgement(criterion_id="disease", verdict="unknown", reason="r", judge_source="rule"),
    ]
    first = check_model_assessment(
        spec,
        {
            "judgements": [
                {"criterion_id": "organism", "verdict": "pass", "evidence_ids": ["ev_ok"], "quote": "Homo sapiens", "reason": "a"},
                {"criterion_id": "assay", "verdict": "pass", "evidence_ids": ["ev_ok"], "quote": "single-cell", "reason": "a"},
                {"criterion_id": "disease", "verdict": "pass", "evidence_ids": ["ev_ok"], "quote": "atherosclerosis", "reason": "a"},
            ]
        },
        EV,
    )
    verify = check_model_assessment(
        spec,
        {
            "judgements": [
                {"criterion_id": "organism", "verdict": "fail", "evidence_ids": ["ev_ok"], "quote": "Homo sapiens", "reason": "b"},
                {"criterion_id": "assay", "verdict": "pass", "evidence_ids": ["ev_ok"], "quote": "single-cell", "reason": "b"},
                {"criterion_id": "disease", "verdict": "pass", "evidence_ids": ["ev_ok"], "quote": "atherosclerosis", "reason": "b"},
            ]
        },
        EV,
    )
    merged, conflicts, review_complete, invalid = merge_final(spec, rules, first, verify)
    assert conflicts
    cat, _ = classify(
        spec,
        merged,
        verified=True,
        conflict=bool(conflicts),
        model_invalid=invalid,
        depth_complete=True,
        review_complete=review_complete,
    )
    assert cat == "needs_review"


def test_valid_evidenced_judgements_can_recommend():
    spec = _spec()
    judgements = [
        CriterionJudgement(
            criterion_id="organism",
            verdict="pass",
            evidence_ids=["ev_ok"],
            quote="Homo sapiens",
            reason="摘要物种匹配",
            judge_source="verify",
        ),
        CriterionJudgement(
            criterion_id="assay",
            verdict="pass",
            evidence_ids=["ev_ok"],
            quote="single-cell",
            reason="单细胞表述",
            judge_source="verify",
        ),
        CriterionJudgement(
            criterion_id="disease",
            verdict="pass",
            evidence_ids=["ev_ok"],
            quote="atherosclerosis",
            reason="疾病词",
            judge_source="verify",
        ),
    ]
    cat, _ = classify(
        spec,
        judgements,
        verified=True,
        conflict=False,
        model_invalid=False,
        depth_complete=True,
        review_complete=True,
    )
    assert cat == "recommended"


def test_all_unknown_without_hard_is_review():
    spec = ResearchSpec(original_request="find datasets")
    judgements = [CriterionJudgement(criterion_id="x", verdict="unknown", reason="n")]
    cat, _ = classify(spec, judgements, verified=True, conflict=False, model_invalid=False)
    assert cat == "needs_review"


def test_weak_rule_pass_not_inherited_when_model_missing():
    spec = _spec()
    rules = [
        CriterionJudgement(
            criterion_id="organism",
            verdict="pass",
            reason="文本出现人",
            support_text="human",
            judge_source="rule",
            clue_only=False,
        ),
        CriterionJudgement(criterion_id="assay", verdict="pass", reason="词", support_text="scrna", judge_source="rule"),
        CriterionJudgement(criterion_id="disease", verdict="pass", reason="词", support_text="atherosclerosis", judge_source="rule"),
    ]
    merged, _conflicts, review_complete, _invalid = merge_final(spec, rules, None, None)
    cat, _ = classify(
        spec,
        merged,
        verified=True,
        conflict=False,
        model_invalid=False,
        depth_complete=True,
        review_complete=review_complete,
    )
    assert cat != "recommended"


def test_illegal_verdict_marks_model_invalid():
    spec = _spec()
    checked = check_model_assessment(
        spec,
        {"judgements": [{"criterion_id": "organism", "verdict": "maybe", "evidence_ids": ["ev_ok"], "quote": "Homo sapiens"}]},
        EV,
    )
    assert checked.invalid
    assert "maybe" in (checked.error or "").lower() or "模型输出无效" in (checked.error or "")
    organism = next(j for j in checked.judgements if j.criterion_id == "organism")
    assert organism.verdict == "unknown"


def test_title_only_groups_fail_becomes_unknown():
    spec = _spec_with_groups()
    evidence = [
        {"evidence_id": "ev_title", "field_path": "esummary.title", "text": "Stem Cell-Derived Vessels-on-Chip for Cardiovascular Disease Modeling"},
        {"evidence_id": "ev_ok", "field_path": "esummary.taxon", "text": "Homo sapiens single-cell RNA sequencing atherosclerosis"},
    ]
    raw = {
        "judgements": [
            {
                "criterion_id": "groups",
                "verdict": "fail",
                "evidence_ids": ["ev_title"],
                "quote": "Vessels-on-Chip",
                "reason": "摘要没有 lesion/control",
            },
            {"criterion_id": "organism", "verdict": "pass", "evidence_ids": ["ev_ok"], "quote": "Homo sapiens", "reason": "ok"},
            {"criterion_id": "assay", "verdict": "unknown", "evidence_ids": [], "reason": "x"},
            {"criterion_id": "disease", "verdict": "unknown", "evidence_ids": [], "reason": "x"},
        ]
    }
    checked = check_model_assessment(spec, raw, evidence, samples=[])
    assert not checked.invalid
    groups = next(j for j in checked.judgements if j.criterion_id == "groups")
    assert groups.verdict == "unknown"
    assert groups.clue_only
    cat, _ = classify(
        spec,
        checked.judgements,
        verified=False,
        conflict=False,
        model_invalid=False,
        depth_complete=False,
        review_complete=False,
    )
    assert cat != "excluded"


def test_sample_evidence_groups_fail_stays():
    spec = _spec_with_groups()
    evidence = [
        {
            "evidence_id": "ev_gsm",
            "field_path": "soft.sample.GSM1.record",
            "text": "GSM1 source_name=HUVEC characteristics=treatment: vehicle",
        }
    ]
    raw = {
        "judgements": [
            {
                "criterion_id": "groups",
                "verdict": "fail",
                "evidence_ids": ["ev_gsm"],
                "quote": "treatment: vehicle",
                "reason": "样本只有处理组，没有 lesion/control 组织分组",
            },
            {"criterion_id": "organism", "verdict": "unknown", "evidence_ids": [], "reason": "x"},
            {"criterion_id": "assay", "verdict": "unknown", "evidence_ids": [], "reason": "x"},
            {"criterion_id": "disease", "verdict": "unknown", "evidence_ids": [], "reason": "x"},
        ]
    }
    samples = [{"gsm": "GSM1", "source_name": "HUVEC", "characteristics": [{"key": "treatment", "value": "vehicle"}]}]
    checked = check_model_assessment(spec, raw, evidence, samples=samples)
    groups = next(j for j in checked.judgements if j.criterion_id == "groups")
    assert groups.verdict == "fail"


def test_judge_payload_includes_sample_records():
    spec = _spec()
    payload = judge_user_payload(
        spec,
        "GSE1",
        summary={"title": "t", "n_samples": 2},
        evidence=[],
        samples=[
            {
                "gsm": "GSM1",
                "title": "donor A lesion",
                "organism": "Homo sapiens",
                "source_name": "plaque",
                "donor_key": "A",
                "group_label": "lesion",
                "library_strategy": "RNA-Seq",
                "library_source": "transcriptomic",
                "characteristics": [{"key": "age", "value": "60"}],
            }
        ],
    )
    assert payload["sample_records_available"] is True
    assert payload["samples"][0]["gsm"] == "GSM1"
    assert payload["samples"][0]["donor_key"] == "A"
    assert payload["sample_coverage"] == {"total": 1, "included": 1, "complete": True}
    empty = judge_user_payload(spec, "GSE1", summary={}, evidence=[], samples=[])
    assert empty["sample_records_available"] is False
    assert empty["samples"] == []
    assert empty["sample_coverage"]["complete"] is True


def test_judge_payload_strips_sample_evidence():
    spec = _spec()
    evidence = [
        {"evidence_id": "ev_sum", "field_path": "esummary.summary", "text": "Homo sapiens atherosclerosis"},
        {"evidence_id": "ev_gsm", "field_path": "soft.sample.GSM1.record", "text": "GSM1 lesion donor A"},
    ]
    payload = judge_user_payload(
        spec,
        "GSE1",
        summary={"title": "t"},
        evidence=evidence,
        samples=[{"gsm": "GSM1", "title": "lesion donor A", "characteristics": []}],
    )
    assert [row["evidence_id"] for row in payload["evidence"]] == ["ev_sum"]
    assert payload["samples"][0]["evidence_id"] == "ev_gsm"


def test_fit_samples_records_incomplete_coverage():
    from app.pipeline.assessment import fit_samples

    samples = [{"gsm": f"GSM{i}", "title": "x" * 80, "characteristics": []} for i in range(6)]
    included, coverage = fit_samples(samples, budget=200)
    assert coverage["total"] == 6
    assert 0 < coverage["included"] < 6
    assert coverage["complete"] is False
    assert len(included) == coverage["included"]


def test_source_conflict_summary_vs_taxon_is_review():
    spec = _spec()
    evidence = [
        {
            "evidence_id": "ev_sum",
            "field_path": "esummary.summary",
            "text": "This murine disease model of atherosclerosis was used to study plaque.",
        },
        {"evidence_id": "ev_tax", "field_path": "esummary.taxon", "text": "Homo sapiens"},
    ]
    raw = {
        "judgements": [
            {
                "criterion_id": "disease",
                "verdict": "fail",
                "evidence_ids": ["ev_sum"],
                "quote": "murine disease model",
                "reason": "小鼠模型",
            },
            {"criterion_id": "organism", "verdict": "pass", "evidence_ids": ["ev_tax"], "quote": "Homo sapiens", "reason": "ok"},
            {"criterion_id": "assay", "verdict": "unknown", "evidence_ids": [], "reason": "x"},
        ]
    }
    checked = check_model_assessment(spec, raw, evidence, samples=[], study={"taxon": "Homo sapiens"})
    disease = next(j for j in checked.judgements if j.criterion_id == "disease")
    assert disease.verdict == "unknown"
    assert disease.clue_only
    assert "来源冲突" in disease.reason
    cat, reason = classify(
        spec,
        checked.judgements,
        verified=True,
        conflict=False,
        model_invalid=False,
        depth_complete=True,
        review_complete=True,
    )
    assert cat != "excluded"


def test_model_invalid_reason_is_verify_failure():
    spec = _spec()
    judgements = [
        CriterionJudgement(criterion_id="organism", verdict="unknown", reason="模型输出无效"),
        CriterionJudgement(criterion_id="assay", verdict="unknown", reason="模型输出无效"),
        CriterionJudgement(criterion_id="disease", verdict="unknown", reason="模型输出无效"),
    ]
    cat, reason = classify(spec, judgements, verified=False, conflict=False, model_invalid=True)
    assert cat == "needs_review"
    assert "复核失败" in reason
    assert "科研信息不足" in reason
    assert reason.startswith("复核失败")


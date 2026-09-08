import pytest

from app.pipeline.assay import assay_relation, infer_sample_assay
from app.pipeline.assessment import _restrict_to_common_subset
from app.pipeline.spec_parse import heuristic_parse
from app.schemas.spec import CriterionJudgement


@pytest.mark.parametrize(
    "strategy,kind",
    [
        ("ATAC-seq", "epigenomics"),
        ("ChIP-Seq", "epigenomics"),
        ("Bisulfite-Seq", "epigenomics"),
        ("Hi-C", "epigenomics"),
        ("WGS", "other"),
        ("WXS", "other"),
    ],
)
def test_explicit_non_rna_library_cannot_inherit_study_rna(strategy, kind):
    call = infer_sample_assay({"library_strategy": strategy}, {"summary": "bulk RNA-seq and chromatin study"})
    assert call.kind == kind
    assert assay_relation(["rna_seq_generic"], call) == "contradict"


def test_one_claimed_group_subset_is_checked_against_assay():
    spec = heuristic_parse("type 2 diabetes human RNA-seq disease and control")
    samples = [
        {"gsm": "GSM1", "organism": "Homo sapiens", "library_strategy": "ATAC-seq",
         "characteristics": [{"raw": "disease state: T2D", "key": "disease state", "value": "T2D"}]},
        {"gsm": "GSM2", "organism": "Homo sapiens", "library_strategy": "ATAC-seq",
         "characteristics": [{"raw": "disease state: non-T2D", "key": "disease state", "value": "non-T2D"}]},
    ]
    js = [CriterionJudgement(criterion_id=c.criterion_id, verdict="pass", reason="claimed",
            qualifying_gsms=["GSM1", "GSM2"] if c.field == "groups" else []) for c in spec.inclusion_criteria]
    result = _restrict_to_common_subset(spec, js, samples)
    assert next(j for j in result if j.criterion_id == "groups").verdict == "unknown"


def test_valid_rna_subset_in_mixed_study_survives():
    spec = heuristic_parse("type 2 diabetes human RNA-seq disease and control")
    samples = [{"gsm": f"GSM{i}", "organism": "Homo sapiens", "library_strategy": strategy,
                "characteristics": [{"key": "disease state", "value": group, "raw": f"disease state: {group}"}]}
               for i, strategy, group in [(1, "ATAC-seq", "T2D"), (2, "RNA-Seq", "T2D"), (3, "RNA-Seq", "non-T2D")]]
    js = [CriterionJudgement(criterion_id=c.criterion_id, verdict="pass", reason="supported",
            qualifying_gsms=["GSM2", "GSM3"]) for c in spec.inclusion_criteria]
    result = _restrict_to_common_subset(spec, js, samples)
    assert all(j.verdict == "pass" for j in result)


def test_groups_define_cohort_when_disease_evidence_names_cases_only():
    spec = heuristic_parse("type 2 diabetes human RNA-seq disease and control")
    samples = [{"gsm": "CASE", "organism": "Homo sapiens", "library_strategy": "RNA-Seq",
                "characteristics": [{"key": "disease state", "value": "T2D", "raw": "disease state: T2D"}]},
               {"gsm": "CTRL", "organism": "Homo sapiens", "library_strategy": "RNA-Seq",
                "characteristics": [{"key": "disease state", "value": "non-T2D", "raw": "disease state: non-T2D"}]}]
    js = [CriterionJudgement(criterion_id=c.criterion_id, verdict="pass", reason="supported",
            qualifying_gsms=(["CASE", "CTRL"] if c.field == "groups" else ["CASE"] if c.field == "disease" else ["CASE", "CTRL"]))
          for c in spec.inclusion_criteria]
    result = _restrict_to_common_subset(spec, js, samples)
    assert next(j for j in result if j.criterion_id == "groups").verdict == "pass"
    assert next(j for j in result if j.criterion_id == "disease").qualifying_gsms == ["CASE"]

"""Defects found verifying the seventh DeepSeek Flash run (2026-09-25)."""

from __future__ import annotations

from app.pipeline.assessment import COVERAGE_DEMOTION_REASON, merge_final
from app.pipeline.engine import (
    _annotate_reason,
    _batch_confound_note,
    _mixed_species_note,
    _qc_dropped_note,
    _raw_access_note,
    _title_individual_count,
)
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


def test_patient_therapy_field_is_not_an_ex_vivo_treatment():
    from app.pipeline.donors import infer_group_label

    spec = heuristic_parse(UC_TEXT)

    def sample(diagnosis, therapy):
        return {
            "gsm": "GSM1",
            "source_name": "Rectal mucosal biopsy",
            "characteristics": [
                {"key": "tissue", "value": "Rectal mucosal biopsy"},
                {"key": "diagnosis", "value": diagnosis},
                {"key": "initial treatment", "value": therapy},
            ],
        }

    assert infer_group_label(sample("Ulcerative Colitis", "CS-Oral"), spec=spec) == "case"
    assert infer_group_label(sample("Ulcerative Colitis", "5ASA"), spec=spec) == "case"
    assert infer_group_label(sample("Control", "NA"), spec=spec) == "control"
    stimulated = sample("Ulcerative Colitis", "LPS 100 ng/ml")
    stimulated["characteristics"][2]["key"] = "treatment"
    assert infer_group_label(stimulated, spec=spec) is None


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


class _Row:
    independent_donors = None
    biosample_count = 0
    file_listing_checked = False
    matrix_availability = "unknown"


def _breast(gsm: str, disease: str) -> dict:
    return {
        "gsm": gsm,
        "organism": "Homo sapiens",
        "title": f"{gsm} 10x single-cell RNA-seq",
        "source_name": "breast tumor" if disease == "breast cancer" else "normal breast",
        "library_strategy": "RNA-Seq",
        "library_source": "transcriptomic single cell",
        "characteristics": [
            {"key": "tissue", "value": "breast"},
            {"key": "disease", "value": disease},
        ],
    }


def test_reason_names_the_rule_cohort_when_the_model_omits_samples():
    spec = heuristic_parse(BR_TEXT)
    cases = [_breast(f"C{i}", "breast cancer") for i in range(6)]
    controls = [_breast(f"N{i}", "normal") for i in range(2)]
    samples = cases + controls
    seen = [s["gsm"] for s in cases[:4] + controls]
    merged = [CriterionJudgement(criterion_id="groups", verdict="pass", reason="m", qualifying_gsms=seen)]
    rules = [CriterionJudgement(criterion_id="groups", verdict="pass", reason="r", qualifying_gsms=[s["gsm"] for s in samples])]
    text = _annotate_reason("ok", _Row(), {}, samples, spec=spec, merged=merged, rules=rules)
    assert "case 4 / control 2 个 GSM（模型列出）" in text
    assert "case 6 / control 2" in text
    same = _annotate_reason("ok", _Row(), {}, samples, spec=spec, merged=rules, rules=rules)
    assert "模型列出" not in same
    assert "适用队列：case 6 / control 2 个 GSM。" in same
    unknown = [CriterionJudgement(criterion_id="groups", verdict="unknown", reason="r")]
    silent = _annotate_reason("ok", _Row(), {}, samples, spec=spec, merged=merged, rules=unknown)
    assert "按样本字段规则" not in silent


def test_merge_leaves_caller_rules_whole():
    spec = heuristic_parse(UC_TEXT)
    everyone = [f"GSM{i}" for i in range(6)]
    rule = CriterionJudgement(
        criterion_id="tissue", verdict="pass", reason="r", qualifying_gsms=list(everyone), support_text="colon"
    )
    model = [CriterionJudgement(criterion_id="groups", verdict="pass", reason="m", qualifying_gsms=everyone[:3])]
    merge_final(spec, [rule], _assessment(model), _assessment(model), samples=[{"gsm": g} for g in everyone])
    assert rule.qualifying_gsms == everyone


def test_breast_subtype_tissue_labels_are_cases():
    from app.pipeline.donors import infer_group_label

    spec = heuristic_parse(BR_TEXT)

    def sample(tissue, cell):
        return {"gsm": "GSM1", "characteristics": [{"key": "tissue", "value": tissue}, {"key": "cell type", "value": cell}]}

    assert infer_group_label(sample("Breast invasive carcinoma", "Breast immune cells"), spec=spec) == "case"
    assert infer_group_label(sample("Breast carcinoma in situ", "Breast stromal cells"), spec=spec) == "case"
    assert infer_group_label(sample("Normal mammary tissues", "Breast immune cells"), spec=spec) == "control"


def test_droplet_libraries_are_not_one_cell_per_gsm():
    from app.pipeline.engine import _single_cell_gsm_note

    cohort = [{"gsm": f"GSM{i}", "library_source": "transcriptomic single cell"} for i in range(50)]
    assert "一个 GSM 多半是一个细胞" in _single_cell_gsm_note(cohort, {"overall_design": "Fluidigm C1 single cells"})
    droplet = {"overall_design": "FACS sorted fractions, then droplet-based 10X scRNAseq (3'HTv3)."}
    assert _single_cell_gsm_note(cohort, droplet) == ""


def test_batch_confound_note():
    def rows(label: str, batches: list[str]) -> tuple[list[dict], dict[str, str]]:
        samples = [{"gsm": f"{label}{i}".upper(), "characteristics": [{"key": "batch", "value": b}]} for i, b in enumerate(batches)]
        return samples, {s["gsm"]: label for s in samples}

    partial, labels = rows("case", ["batch 1"] * 13 + ["batch 2"] * 12 + ["batch 3"])
    controls, control_labels = rows("control", ["batch 3"] * 5 + ["batch 2"] * 3)
    note = _batch_confound_note(partial + controls, labels | control_labels)
    assert "部分重合" in note and "control 多在 batch 3" in note
    split_a, la = rows("case", ["A"] * 4)
    split_b, lb = rows("control", ["B"] * 4)
    assert "完全重合" in _batch_confound_note(split_a + split_b, la | lb)
    even_a, ea = rows("case", ["d1", "d2", "d1", "d2"])
    even_b, eb = rows("control", ["d1", "d2", "d1", "d2"])
    assert _batch_confound_note(even_a + even_b, ea | eb) == ""
    one, lone = rows("case", ["only"] * 4)
    other, lother = rows("control", ["only"] * 4)
    assert _batch_confound_note(one + other, lone | lother) == ""


def test_qc_dropped_and_raw_access_notes():
    dropped = [{"gsm": "A", "characteristics": [{"key": "celltype", "value": "dropped"}]}]
    kept = [{"gsm": "B", "characteristics": [{"key": "celltype", "value": "beta"}]}]
    subset = [{"gsm": "C", "characteristics": [{"key": "in_ins_filtered_data_subset", "value": "FALSE"}]}]
    assert _qc_dropped_note(dropped + kept) == '1/2 个 GSM 被提交者标为质控剔除（“celltype: dropped”），下载后应按该字段过滤。'
    assert "1/1 个 GSM 不在提交者的分析子集里" in _qc_dropped_note(subset)
    assert "不在" not in _qc_dropped_note(dropped + kept)
    assert _qc_dropped_note(kept) == ""
    withheld = {"overall_design": "Raw files for human samples were not submitted to GEO."}
    assert "未公开或需受控申请" in _raw_access_note(withheld)
    assert "未公开或需受控申请" in _raw_access_note({"summary": "Accession phs001234."})
    assert _raw_access_note({"summary": "Raw data are available at GEO."}) == ""

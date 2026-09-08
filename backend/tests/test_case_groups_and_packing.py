import json

import pytest

from app.pipeline.assessment import fit_samples, judge_user_payload
from app.pipeline.donors import infer_group_label
from app.pipeline.spec_parse import heuristic_parse


def sample(label, gsm="GSM1", key="disease state"):
    return {"gsm": gsm, "organism": "Homo sapiens", "library_strategy": "RNA-Seq",
            "characteristics": [{"key": key, "value": label, "raw": f"{key}: {label}"}]}


@pytest.mark.parametrize("disease,label", [("type 2 diabetes", "T2D"), ("type 2 diabetes", "T2DM"),
    ("rheumatoid arthritis", "RA"), ("rheumatoid arthritis", "Rheumatiod Arthritis"),
    ("Alzheimer disease", "sAD"), ("Alzheimer disease", "LOAD"), ("COVID-19", "SARS-CoV-2")])
def test_disease_labels_map_to_case(disease, label):
    spec = heuristic_parse(disease + " human RNA-seq disease and control")
    assert spec.required_groups == ["case", "control"]
    row = sample(label)
    row["group_label"] = "control"
    assert infer_group_label(row, spec=spec) == "case"
    assert infer_group_label(sample("Control"), spec=spec) == "control"


def test_patient_alone_is_not_a_target_disease():
    spec = heuristic_parse("human rheumatoid arthritis disease and control RNA-seq")
    assert infer_group_label({"title": "patient 1"}, spec=spec) is None
    assert infer_group_label(sample("T2DM"), spec=spec) is None
    assert infer_group_label({"title": "healthy control patient 1"}, spec=spec) == "control"
    assert infer_group_label(sample("no RA"), spec=spec) == "control"
    assert infer_group_label({"title": "untreated control"}, spec=spec) is None


def test_explicit_lesion_request_is_preserved():
    spec = heuristic_parse("human atherosclerosis lesion vs control")
    assert spec.required_groups == ["lesion", "control"]
    assert infer_group_label(sample("atherosclerotic lesion"), spec=spec) == "lesion"


def test_limited_input_contains_both_groups_and_reports_incomplete():
    spec = heuristic_parse("human type 2 diabetes RNA-seq disease and control")
    rows = [sample("T2DM", f"GSM{i}") for i in range(50)] + [sample("Control", f"GSM{i}") for i in range(50, 100)]
    packed, coverage = fit_samples(rows, spec=spec, budget=1200)
    assert {s["group_label"] for s in packed[:2]} == {"case", "control"}
    assert not coverage["complete"]
    assert len(json.dumps(packed, ensure_ascii=False)) <= 1200


def test_oversized_sample_is_not_silently_sent_over_budget():
    row = sample("T2D")
    row["title"] = "x" * 1000
    packed, coverage = fit_samples([row], budget=200)
    assert packed == [] and not coverage["complete"]


def test_group_inventory_is_not_a_donor_count():
    spec = heuristic_parse("human type 2 diabetes RNA-seq disease and control")
    rows = [sample("T2D"), sample("Control", "GSM2")]
    data = judge_user_payload(spec, "GSE1", summary={}, evidence=[], samples=rows)
    assert data["group_inventory"]["gsm_counts"] == {"case": 1, "control": 1}
    assert "anatomical" in data["group_definitions"]["case"]
    assert "donor counts" in data["group_inventory"]["note"]

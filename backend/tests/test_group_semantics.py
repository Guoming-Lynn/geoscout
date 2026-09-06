from app.pipeline.donors import donor_criterion_judgement, donors_per_group, infer_group_label
from app.schemas.spec import Criterion


def _chars(pairs: list[tuple[str, str]], **extra) -> dict:
    chars = [{"key": k, "value": v, "raw": f"{k}: {v}"} for k, v in pairs]
    out = {"characteristics": chars, "donor_key": extra.get("donor_key"), "gsm": extra.get("gsm", "GSM1")}
    if extra.get("title"):
        out["title"] = extra["title"]
    return out


def _group(value: str) -> dict:
    return _chars([("group", value)])


def _crit(n: int = 3) -> Criterion:
    return Criterion(
        criterion_id="donors_per_group",
        field="donors",
        description="每组最少独立供体",
        user_text=str(n),
        priority="hard",
        value=n,
    )


def test_abnormal_is_not_healthy_control():
    assert infer_group_label(_group("abnormal")) != "control"
    assert infer_group_label(_group("abnormal"), required_groups=["lesion", "control"], control_type="healthy") is None


def test_uncontrolled_disease_is_not_control():
    assert infer_group_label(_group("uncontrolled disease")) != "control"
    assert infer_group_label(_group("uncontrolled disease")) == "lesion"


def test_untreated_tumor_not_healthy_when_healthy_vs_tumor():
    sample = _chars([("disease", "tumor"), ("treatment", "untreated")])
    label = infer_group_label(sample, required_groups=["lesion", "control"], control_type="healthy")
    assert label != "control"
    assert label == "lesion"
    blob = infer_group_label(_group("untreated tumor"), required_groups=["lesion", "control"], control_type="healthy")
    assert blob == "lesion"


def test_treatment_contrast_groups_by_treatment_and_keeps_tumor():
    untreated = _chars([("disease", "tumor"), ("treatment", "untreated")])
    treated = _chars([("disease", "tumor"), ("treatment", "treated")])
    assert infer_group_label(untreated, required_groups=["treated", "untreated"]) == "untreated"
    assert infer_group_label(treated, required_groups=["treated", "untreated"]) == "treated"


def test_multifield_tumor_untreated_matches_combined_phrase():
    multi = _chars([("disease", "tumor"), ("treatment", "untreated")])
    combined = _group("untreated tumor")
    groups = ["lesion", "control"]
    assert infer_group_label(multi, required_groups=groups, control_type="healthy") == infer_group_label(
        combined, required_groups=groups, control_type="healthy"
    )


def test_control_types_are_not_interchangeable():
    healthy = _group("healthy control")
    adjacent = _group("normal adjacent tissue")
    untreated = _group("untreated")
    wt = _group("WT")
    groups = ["lesion", "control"]
    assert infer_group_label(healthy, required_groups=groups, control_type="healthy") == "control"
    assert infer_group_label(adjacent, required_groups=groups, control_type="healthy") != "control"
    assert infer_group_label(untreated, required_groups=groups, control_type="healthy") != "control"
    assert infer_group_label(wt, required_groups=groups, control_type="healthy") != "control"
    assert infer_group_label(adjacent, required_groups=groups, control_type="adjacent") == "control"
    assert infer_group_label(healthy, required_groups=groups, control_type="adjacent") != "control"
    assert infer_group_label(untreated, required_groups=groups, control_type="untreated") == "control"
    assert infer_group_label(healthy, required_groups=groups, control_type="untreated") != "control"
    assert infer_group_label(wt, required_groups=groups, control_type="wt") == "control"
    assert infer_group_label(healthy, required_groups=groups, control_type="wt") != "control"


def test_donor_counts_do_not_put_untreated_tumor_in_control():
    samples = [
        _chars([("disease", "tumor"), ("treatment", "untreated")], donor_key="T1", gsm="GSM1"),
        _chars([("disease", "tumor"), ("treatment", "untreated")], donor_key="T2", gsm="GSM2"),
        _chars([("disease", "tumor"), ("treatment", "untreated")], donor_key="T3", gsm="GSM3"),
        _chars([("group", "healthy control")], donor_key="C1", gsm="GSM4"),
        _chars([("group", "healthy control")], donor_key="C2", gsm="GSM5"),
        _chars([("group", "healthy control")], donor_key="C3", gsm="GSM6"),
    ]
    stats = donors_per_group(samples, ["lesion", "control"], control_type="healthy")
    assert stats["counts"]["lesion"] == 3
    assert stats["counts"]["control"] == 3
    j = donor_criterion_judgement(_crit(3), samples, ["lesion", "control"], control_type="healthy")
    assert j.verdict == "pass"


def test_untreated_alone_is_not_default_control():
    assert infer_group_label(_group("untreated")) is None

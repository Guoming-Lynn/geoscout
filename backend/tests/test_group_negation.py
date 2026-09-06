from app.pipeline.donors import infer_group_label


def _group(value: str) -> dict:
    return {"characteristics": [{"key": "group", "value": value, "raw": f"group: {value}"}]}


def test_no_disease_is_not_lesion():
    assert infer_group_label(_group("no disease")) != "lesion"
    assert infer_group_label(_group("non-diseased")) != "lesion"
    assert infer_group_label(_group("non-disease")) != "lesion"
    assert infer_group_label(_group("without disease")) != "lesion"
    assert infer_group_label(_group("disease-free")) != "lesion"


def test_negated_disease_is_control_after_normalize():
    assert infer_group_label(_group("NO  DISEASE")) == "control"
    assert infer_group_label(_group("Non-Diseased")) == "control"
    assert infer_group_label(_group("disease free")) == "control"


def test_explicit_control_phrases():
    assert infer_group_label(_group("healthy control")) == "control"
    assert infer_group_label(_group("normal adjacent tissue")) == "control"
    assert infer_group_label(_group("untreated")) is None


def test_explicit_lesion_still_lesion():
    assert infer_group_label(_group("atherosclerotic lesion")) == "lesion"
    assert infer_group_label(_group("HGPS")) == "lesion"


def test_ambiguous_group_is_unknown():
    assert infer_group_label(_group("other")) is None
    assert infer_group_label(_group("unknown")) is None
    assert infer_group_label(_group("n/a")) is None

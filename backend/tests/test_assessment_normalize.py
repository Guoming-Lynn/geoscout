from app.connectors.llm import LLMError, normalize_model_assessment_payload, validate_assessment


def test_unwrap_assessments_key():
    raw = {
        "assessments": [
            {"criterion_id": "organism", "verdict": "PASS", "evidence_ids": ["ev_ok"], "quote": "Homo"}
        ]
    }
    model = validate_assessment(raw)
    assert model.judgements[0].verdict == "pass"
    assert model.judgements[0].criterion_id == "organism"


def test_unwrap_nested_assess_dataset():
    raw = {
        "assess_dataset": {
            "judgements": [{"criterion_id": "assay", "verdict": "fail", "evidence_ids": [], "reason": "bulk"}]
        }
    }
    model = validate_assessment(raw)
    assert model.judgements[0].criterion_id == "assay"


def test_null_quote_coerced():
    model = validate_assessment(
        {
            "judgements": [
                {"criterion_id": "organism", "verdict": "unknown", "evidence_ids": [], "quote": None, "reason": None}
            ]
        }
    )
    assert model.judgements[0].quote == ""
    assert model.judgements[0].reason == ""


def test_flat_criterion_map_unwraps():
    payload = normalize_model_assessment_payload({"organism": "pass", "assay": "unknown", "disease": "fail"})
    assert {row["criterion_id"] for row in payload["judgements"]} == {"organism", "assay", "disease"}


def test_illegal_verdict_raises():
    try:
        validate_assessment({"judgements": [{"criterion_id": "organism", "verdict": "maybe"}]})
    except LLMError:
        return
    raise AssertionError("illegal verdict must not coerce to unknown")


def test_result_alias_maps_to_verdict():
    model = validate_assessment(
        {"judgements": [{"criterion_id": "organism", "result": "通过", "evidence_ids": [], "quote": "", "reason": ""}]}
    )
    assert model.judgements[0].verdict == "pass"


def test_missing_verdict_not_coerced_to_unknown():
    try:
        validate_assessment({"judgements": [{"criterion_id": "organism", "evidence_ids": [], "quote": ""}]})
    except LLMError:
        return
    raise AssertionError("missing verdict must not become unknown")


def test_unwrap_inclusion_criteria_eval_list():
    raw = {
        "inclusion_criteria_eval": [
            {"criterion_id": "organism", "verdict": "pass", "evidence_ids": ["ev_ok"], "quote": "Homo", "reason": ""}
        ],
        "evidence_id": None,
    }
    model = validate_assessment(raw)
    assert model.judgements[0].criterion_id == "organism"
    assert model.judgements[0].verdict == "pass"


def test_unwrap_inclusion_criteria_eval_dict():
    raw = {
        "inclusion_criteria_eval": {
            "organism": {"verdict": "pass", "quote": "Homo", "reason": ""},
            "assay": {"verdict": "unknown", "quote": "", "reason": "bulk"},
        },
        "evidence_id": None,
    }
    model = validate_assessment(raw)
    by_id = {row.criterion_id: row.verdict for row in model.judgements}
    assert by_id["organism"] == "pass"
    assert by_id["assay"] == "unknown"


def test_spec_inclusion_criteria_not_treated_as_judgements():
    raw = {
        "inclusion_criteria": [
            {
                "criterion_id": "organism",
                "field": "organism",
                "description": "物种必须匹配",
                "priority": "hard",
            }
        ],
        "evidence_id": [],
    }
    try:
        validate_assessment(raw)
    except LLMError:
        return
    raise AssertionError("spec dump must remain invalid so format repair can run")

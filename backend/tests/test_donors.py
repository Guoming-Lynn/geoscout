from app.pipeline.donors import donor_criterion_judgement, donors_per_group
from app.schemas.spec import Criterion


def _sample(gsm: str, donor: str | None, group: str | None, organism: str = "Homo sapiens", extra_libs: int = 0) -> dict:
    chars = []
    if donor:
        chars.append({"key": "donor_id", "value": donor, "raw": f"donor_id: {donor}"})
    if group:
        chars.append({"key": "group", "value": group, "raw": f"group: {group}"})
    return {
        "gsm": gsm,
        "donor_key": f"donor_id={donor}" if donor else None,
        "organism": organism,
        "characteristics": chars,
    }


def _crit(n: int = 3) -> Criterion:
    return Criterion(
        criterion_id="donors_per_group",
        field="donors",
        description="每组最少独立供体",
        user_text=str(n),
        priority="hard",
        value=n,
    )


def test_case_six_control_zero_fails_per_group():
    samples = [_sample(f"GSM{i}", f"C{i}", "lesion") for i in range(6)]
    j = donor_criterion_judgement(_crit(3), samples, ["lesion", "control"])
    assert j.verdict == "fail"
    assert "control:0" in (j.support_text or j.reason)


def test_three_and_three_passes():
    samples = [_sample(f"L{i}", f"L{i}", "lesion") for i in range(3)]
    samples += [_sample(f"C{i}", f"C{i}", "control") for i in range(3)]
    j = donor_criterion_judgement(_crit(3), samples, ["lesion", "control"])
    assert j.verdict == "pass"


def test_three_libraries_count_as_one_donor():
    samples = [
        _sample("GSM1", "D1", "lesion"),
        _sample("GSM2", "D1", "lesion"),
        _sample("GSM3", "D1", "lesion"),
        _sample("GSM4", "C1", "control"),
        _sample("GSM5", "C2", "control"),
        _sample("GSM6", "C3", "control"),
    ]
    stats = donors_per_group(samples, ["lesion", "control"])
    assert stats["counts"]["lesion"] == 1
    j = donor_criterion_judgement(_crit(3), samples, ["lesion", "control"])
    assert j.verdict == "fail"


def test_missing_group_is_unknown():
    samples = [_sample(f"GSM{i}", f"D{i}", None) for i in range(6)]
    j = donor_criterion_judgement(_crit(3), samples, ["lesion", "control"])
    assert j.verdict == "unknown"
    assert "分组" in j.reason


def test_missing_donor_is_unknown():
    samples = [_sample(f"GSM{i}", None, "lesion" if i < 3 else "control") for i in range(6)]
    j = donor_criterion_judgement(_crit(3), samples, ["lesion", "control"])
    assert j.verdict == "unknown"
    assert "供体" in j.reason


def test_truncated_cannot_fail_for_shortage():
    samples = [_sample("GSM1", "D1", "lesion")]
    j = donor_criterion_judgement(_crit(3), samples, ["lesion", "control"], truncated=True)
    assert j.verdict == "unknown"
    assert "未完整" in j.reason


def test_paired_donor_counts_in_each_group_not_as_two_global():
    samples = [
        _sample("GSM1", "P1", "lesion"),
        _sample("GSM2", "P1", "control"),
        _sample("GSM3", "P2", "lesion"),
        _sample("GSM4", "P2", "control"),
        _sample("GSM5", "P3", "lesion"),
        _sample("GSM6", "P3", "control"),
    ]
    stats = donors_per_group(samples, ["lesion", "control"])
    assert stats["counts"]["lesion"] == 3
    assert stats["counts"]["control"] == 3
    j = donor_criterion_judgement(_crit(3), samples, ["lesion", "control"])
    assert j.verdict == "pass"
    assert "不计为两个全局供体" in j.reason


def test_mixed_organism_counts_only_matching_subset():
    samples = [_sample(f"H{i}", f"H{i}", "lesion", "Homo sapiens") for i in range(3)]
    samples += [_sample(f"M{i}", f"M{i}", "control", "Mus musculus") for i in range(3)]
    stats = donors_per_group(samples, ["lesion", "control"], organisms=["Homo sapiens"])
    assert stats["counts"]["lesion"] == 3
    assert stats["counts"]["control"] == 0
    j = donor_criterion_judgement(_crit(3), samples, ["lesion", "control"], organisms=["Homo sapiens"])
    assert j.verdict == "fail"

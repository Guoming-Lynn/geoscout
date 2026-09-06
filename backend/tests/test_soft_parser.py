from pathlib import Path

from app.evidence.soft_parser import count_independent_donors, parse_soft_text, series_as_dict

FIXTURE = Path(__file__).parent / "fixtures" / "GSE1000_metadata.soft"


def test_soft_skips_tables_and_counts_donors():
    doc = parse_soft_text(FIXTURE.read_text(encoding="utf-8"))
    parsed = series_as_dict(doc)
    assert parsed["gse"] == "GSE1000"
    assert doc.tables_skipped == 1
    samples = parsed["samples"]
    assert len(samples) == 3
    # D1 appears twice and must not be counted twice.
    human = [s for s in samples if s["organism"] == "Homo sapiens"]
    assert count_independent_donors(human) == 1
    organisms = {s["organism"] for s in samples}
    assert organisms == {"Homo sapiens", "Mus musculus"}


def test_truncation_flag():
    doc = parse_soft_text(FIXTURE.read_text(encoding="utf-8"), max_samples=1)
    assert doc.truncated
    assert doc.truncate_reason == "max_samples"
    assert len(doc.samples) == 1

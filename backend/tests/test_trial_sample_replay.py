import json
import sqlite3
from pathlib import Path

import pytest

from app.pipeline.assessment import applicable_gsms
from app.pipeline.screening import classify, rule_judgements
from app.pipeline.spec_parse import heuristic_parse

FIXTURE = Path(__file__).parent / "fixtures" / "trial_sample_replay.json"
CACHE_DB = Path(__file__).resolve().parents[2] / "data" / "disease-live-lowmed-20260908" / "runtime" / "geoscout.db"


def _method(spec, study, samples=None):
    return next(j for j in rule_judgements(spec, study, samples or []) if j.criterion_id == "assay_method")


def _from_fixture(gse: str) -> tuple[dict, list[dict], dict[str, int]]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    row = payload["series"][gse]
    return row["study"], [_coerce_sample(sample) for sample in row["samples"]], dict(row["strategy_counts"])


def _coerce_sample(row: dict) -> dict:
    sample = dict(row)
    sample.setdefault("library_source", "")
    sample.setdefault("protocol", "")
    sample.setdefault("protocol_fields", {})
    sample.setdefault("characteristics", [])
    sample.setdefault("donor_key", None)
    sample.setdefault("group_label", None)
    sample.setdefault("coverage_incomplete", False)
    return sample


PRODUCTION_SAMPLE_KEYS = (
    "gsm",
    "title",
    "organism",
    "source_name",
    "library_strategy",
    "library_source",
    "protocol",
    "protocol_fields",
    "characteristics",
)


def _sample_from_row(row: sqlite3.Row) -> dict:
    attrs = json.loads(row["attrs_json"] or "{}")
    return {
        "gsm": row["gsm"],
        "title": row["title"] or "",
        "organism": row["organism"] or "",
        "source_name": row["source_name"] or "",
        "donor_key": row["donor_key"],
        "group_label": row["group_label"],
        "library_strategy": attrs.get("library_strategy") or row["library_strategy"] or "",
        "library_source": attrs.get("library_source") or "",
        "protocol": attrs.get("protocol") or "",
        "protocol_fields": attrs.get("protocol_fields") or {},
        "characteristics": json.loads(row["characteristics_json"] or "[]"),
        "coverage_incomplete": bool(row["coverage_incomplete"]),
    }


def _from_cache(gse: str) -> tuple[dict, list[dict], dict[str, int]] | None:
    if not CACHE_DB.exists():
        return None
    con = sqlite3.connect(f"file:{CACHE_DB.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    ds = con.execute(
        "select title, taxon, gdstype from datasets where gse=?",
        [gse],
    ).fetchone()
    if ds is None:
        return None
    samples = [
        _sample_from_row(row)
        for row in con.execute(
            """
            select gsm, title, organism, source_name, library_strategy, donor_key, group_label,
                   characteristics_json, attrs_json, coverage_incomplete
            from samples where gse=? order by gsm
            """,
            [gse],
        )
    ]
    counts = {
        row["library_strategy"] or "": row["c"]
        for row in con.execute(
            "select library_strategy, count(*) c from samples where gse=? group by library_strategy",
            [gse],
        )
    }
    if not samples:
        return None
    study = {"title": ds["title"], "taxon": ds["taxon"], "gdstype": ds["gdstype"]}
    return study, samples, counts


def load_series(gse: str) -> tuple[dict, list[dict], dict[str, int]]:
    cached = _from_cache(gse)
    if cached:
        return cached
    return _from_fixture(gse)


def test_replay_samples_include_production_judgement_fields():
    _, samples, _ = load_series("GSE226875")
    assert samples
    for row in samples:
        for key in PRODUCTION_SAMPLE_KEYS:
            assert key in row, key
        assert isinstance(row["protocol"], str)
        assert isinstance(row["protocol_fields"], dict)
        assert isinstance(row["characteristics"], list)
    fixture_study, fixture_samples, _ = _from_fixture("GSE226875")
    assert fixture_study["title"]
    assert fixture_samples
    for row in fixture_samples:
        for key in PRODUCTION_SAMPLE_KEYS:
            assert key in row, key


def test_cached_atac_gsms_qualify_and_chip_gsms_do_not():
    spec = heuristic_parse("human intestinal tissue ATAC-seq")
    study, samples, _ = load_series("GSE282442")
    judged = _method(spec, study, samples)
    assert samples
    assert all(row["library_strategy"] == "ATAC-seq" for row in samples)
    assert judged.verdict == "pass"
    assert set(judged.qualifying_gsms) == {row["gsm"] for row in samples}

    chip_study, chip_samples, _ = load_series("GSE332645")
    chip = _method(spec, chip_study, chip_samples)
    assert chip_samples
    assert all(str(row["library_strategy"]).lower() == "chip-seq" for row in chip_samples)
    assert chip.verdict == "fail"
    assert not chip.qualifying_gsms


def test_cached_chromatin_title_uses_sample_library_not_title():
    spec = heuristic_parse("human intestinal tissue ATAC-seq")
    open_study, open_samples, _ = load_series("GSE319550")
    title_only = _method(spec, open_study)
    assert title_only.verdict == "unknown"
    with_samples = _method(spec, open_study, open_samples)
    assert with_samples.verdict == "pass"
    assert set(with_samples.qualifying_gsms) == {row["gsm"] for row in open_samples}
    assert all(row["library_strategy"] == "ATAC-seq" for row in open_samples)

    rna_study, rna_samples, _ = load_series("GSE226875")
    assert "chromatin" in rna_study["title"].lower()
    rna = _method(spec, rna_study, rna_samples)
    assert rna.verdict != "pass"
    assert not rna.qualifying_gsms
    assert all(row["library_strategy"] == "RNA-Seq" for row in rna_samples)


def test_cached_mixed_gsms_only_method_matches_qualify():
    spec = heuristic_parse("human intestinal tissue ATAC-seq")
    atac_study, atac_samples, _ = load_series("GSE282442")
    chip_study, chip_samples, _ = load_series("GSE332645")
    rna_study, rna_samples, _ = load_series("GSE226875")
    mixed_study = {
        "title": f"{atac_study['title']}; {chip_study['title']}",
        "gdstype": atac_study.get("gdstype") or "",
    }
    mixed = atac_samples[:1] + chip_samples[:1] + rna_samples[:1]
    judged = _method(spec, mixed_study, mixed)
    assert judged.verdict == "pass"
    assert judged.qualifying_gsms == [atac_samples[0]["gsm"]]
    assert chip_samples[0]["gsm"] not in judged.qualifying_gsms
    assert rna_samples[0]["gsm"] not in judged.qualifying_gsms

    chip_only = _method(spec, mixed_study, chip_samples[:1] + rna_samples[:1])
    assert chip_only.verdict != "pass"
    assert not chip_only.qualifying_gsms


CONFLICTING_STRATEGIES = {"rna-seq", "ncrna-seq", "mirna-seq", "chip-seq"}


def _strategy_key(sample: dict) -> str:
    return str(sample.get("library_strategy") or "").casefold().replace("_", "-")


def _conflicting_gsms(samples: list[dict]) -> set[str]:
    return {row["gsm"] for row in samples if _strategy_key(row) in CONFLICTING_STRATEGIES}


def _export_slim(samples: list[dict]) -> list[dict]:
    return [
        {
            "gsm": row.get("gsm"),
            "title": row.get("title") or "",
            "organism": row.get("organism") or "",
            "source_name": row.get("source_name") or "",
            "donor_key": row.get("donor_key"),
            "library_strategy": row.get("library_strategy") or "",
            "characteristics": row.get("characteristics") or [],
            "coverage_incomplete": bool(row.get("coverage_incomplete")),
        }
        for row in samples
    ]


def _screen(spec, study, samples, *, verified=True, depth=True):
    judgements = rule_judgements(spec, study, samples)
    category, reason = classify(
        spec,
        judgements,
        verified=verified,
        conflict=False,
        model_invalid=False,
        depth_complete=depth,
        review_complete=True,
    )
    method = next((j for j in judgements if j.criterion_id == "assay_method"), None)
    cohort = applicable_gsms(spec, judgements, samples, study)
    export_cohort = applicable_gsms(spec, judgements, _export_slim(samples), study)
    return {
        "judgements": judgements,
        "category": category,
        "reason": reason,
        "method": method,
        "cohort": cohort,
        "export_cohort": export_cohort,
    }


def test_cached_replay_category_and_export_keep_conflicting_gsms_out():
    spec = heuristic_parse("human intestinal tissue ATAC-seq")
    atac_study, atac_samples, _ = load_series("GSE282442")
    atac = _screen(spec, atac_study, atac_samples)
    assert atac["method"].verdict == "pass"
    assert atac["category"] == "recommended"
    assert set(atac["method"].qualifying_gsms) == {row["gsm"] for row in atac_samples}
    assert set(atac["cohort"]) == {row["gsm"] for row in atac_samples}
    assert atac["export_cohort"] == atac["cohort"]
    assert not _conflicting_gsms(atac_samples)

    chip_study, chip_samples, _ = load_series("GSE332645")
    chip = _screen(spec, chip_study, chip_samples)
    assert chip["method"].verdict == "fail"
    assert chip["category"] == "excluded"
    assert not chip["method"].qualifying_gsms
    assert not chip["cohort"]
    assert not chip["export_cohort"]
    assert _conflicting_gsms(chip_samples) == {row["gsm"] for row in chip_samples}

    rna_study, rna_samples, _ = load_series("GSE226875")
    rna = _screen(spec, rna_study, rna_samples)
    assert rna["method"].verdict != "pass"
    assert rna["category"] == "excluded"
    assert not rna["method"].qualifying_gsms
    assert not rna["cohort"]
    assert not rna["export_cohort"]
    assert all(row["protocol"] for row in rna_samples) or not CACHE_DB.exists()

    mixed_study = {"title": f"{atac_study['title']}; {chip_study['title']}", "gdstype": atac_study.get("gdstype") or ""}
    mixed_samples = atac_samples[:1] + chip_samples[:1] + rna_samples[:1]
    mixed = _screen(spec, mixed_study, mixed_samples)
    assert mixed["category"] == "recommended"
    assert mixed["method"].qualifying_gsms == [atac_samples[0]["gsm"]]
    assert mixed["cohort"] == [atac_samples[0]["gsm"]]
    assert mixed["export_cohort"] == mixed["cohort"]
    assert chip_samples[0]["gsm"] not in mixed["cohort"]
    assert rna_samples[0]["gsm"] not in mixed["cohort"]


def test_visium_rna_seq_strategy_is_not_excluded_by_method_priority():
    spec = heuristic_parse("乳腺癌空间转录组")
    sample = {
        "gsm": "GSM1",
        "title": "Visium section",
        "organism": "Homo sapiens",
        "source_name": "breast tumor",
        "library_strategy": "RNA-Seq",
        "protocol": "10x Genomics Visium spatial gene expression",
    }
    study = {
        "title": "Visium of breast cancer",
        "gdstype": "Expression profiling by high throughput sequencing",
    }
    screened = _screen(spec, study, [sample])
    assay = next(j for j in screened["judgements"] if j.criterion_id == "assay")
    assert assay.verdict == "pass"
    assert screened["category"] != "excluded"


@pytest.mark.skipif(not CACHE_DB.exists(), reason="trial cache missing")
def test_all_cached_series_keep_rna_chip_out_of_atac_cohort():
    spec = heuristic_parse("human intestinal tissue ATAC-seq")
    con = sqlite3.connect(f"file:{CACHE_DB.as_posix()}?mode=ro", uri=True)
    gses = [row[0] for row in con.execute("select distinct gse from samples order by gse")]
    assert gses
    scanned = 0
    for gse in gses:
        loaded = _from_cache(gse)
        if not loaded:
            continue
        study, samples, _ = loaded
        scanned += 1
        screened = _screen(spec, study, samples)
        forbidden = _conflicting_gsms(samples)
        assert not forbidden.intersection(screened["method"].qualifying_gsms), gse
        assert not forbidden.intersection(screened["cohort"]), gse
        assert not forbidden.intersection(screened["export_cohort"]), gse
        if screened["category"] == "recommended":
            assert screened["method"].verdict == "pass"
            assert screened["cohort"]
            assert all(_strategy_key(row) not in CONFLICTING_STRATEGIES for row in samples if row["gsm"] in screened["cohort"])
    assert scanned >= 4

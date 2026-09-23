"""Defects found while hand-checking the third DeepSeek Flash run (2026-09-23)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.connectors import geo_ftp
from app.connectors.geo_ftp import GeoFetchError, GeoFtpClient
from app.pipeline.assay import MICROBIOME_HINTS, _hint_hit, mixed_omics_note
from app.pipeline.donors import donors_per_group
from app.pipeline.engine import _annotate_reason, _title_individual_count
from app.pipeline.screening import rule_gate_ids, rule_judgements
from app.pipeline.source import tissue_matches
from app.pipeline.spec_parse import heuristic_parse

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ROUND2 = json.loads((FIXTURES / "flash_round2_samples.json").read_text(encoding="utf-8"))
ROUND3 = json.loads((FIXTURES / "flash_round3_samples.json").read_text(encoding="utf-8"))
AD = "human primary Alzheimer disease brain RNA-seq with disease and control"
T2D = "human primary type 2 diabetes islet RNA-seq with disease and control"
RA = "human primary rheumatoid arthritis PBMC RNA-seq with disease and control"


def _entry(gse: str) -> tuple[dict, list[dict]]:
    row = ROUND3.get(gse) or ROUND2[gse]
    return row["summary"], row["samples"]


class _Row:
    independent_donors = None
    biosample_count = 24
    file_listing_checked = False
    matrix_availability = "unknown"


def _reason(spec, gse: str) -> str:
    summary, samples = _entry(gse)
    rules = rule_judgements(spec, summary, samples)
    return _annotate_reason("全部硬条件通过。", _Row(), summary, samples, spec=spec, merged=rules)


def test_soft_download_retries_network_errors(monkeypatch):
    monkeypatch.setattr(geo_ftp, "_RETRY_BACKOFF_S", (0.0, 0.0))
    calls = {"n": 0}

    async def flaky(self, url, *, max_bytes=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise GeoFetchError("GEO 文件网络错误: ConnectError", retryable=True)
        return b"^SERIES = GSE1", url

    monkeypatch.setattr(GeoFtpClient, "_fetch_once", flaky)
    data, _ = asyncio.run(GeoFtpClient().fetch_bytes("https://ftp.ncbi.nlm.nih.gov/geo/x"))
    assert data.startswith(b"^SERIES")
    assert calls["n"] == 3


def test_soft_download_does_not_retry_missing_file(monkeypatch):
    monkeypatch.setattr(geo_ftp, "_RETRY_BACKOFF_S", (0.0, 0.0))
    calls = {"n": 0}

    async def missing(self, url, *, max_bytes=None):
        calls["n"] += 1
        raise GeoFetchError("GEO 文件 HTTP 404", 404)

    monkeypatch.setattr(GeoFtpClient, "_fetch_once", missing)
    with pytest.raises(GeoFetchError):
        asyncio.run(GeoFtpClient().fetch_bytes("https://ftp.ncbi.nlm.nih.gov/geo/x"))
    assert calls["n"] == 1


def test_donors_per_group_counts_disease_cases():
    t2d = heuristic_parse(T2D)
    _, islets = _entry("GSE81608")
    counts = donors_per_group(islets, t2d.required_groups, spec=t2d)["counts"]
    assert counts["case"] > 0 and counts["control"] > 0
    ra = heuristic_parse(RA)
    _, tscm = _entry("GSE309906")
    assert donors_per_group(tscm, ra.required_groups, spec=ra)["counts"] == {"case": 3, "control": 5}


def test_mitochondrial_16s_depletion_is_not_microbiome():
    ad = heuristic_parse(AD)
    summary, samples = _entry("GSE318560")
    assay = next(item for item in rule_judgements(ad, summary, samples) if item.criterion_id == "assay")
    assert assay.verdict == "pass"
    assert "microbiome" not in mixed_omics_note(summary, samples)
    assert "适用队列：case 6 / control 5 个 GSM。" in _reason(ad, "GSE318560")
    assert _hint_hit("16S rRNA gene amplicon sequencing of stool", MICROBIOME_HINTS) == "16s"
    assert _hint_hit("mitochondrial rRNA (m12S and m16S) were cleaved", MICROBIOME_HINTS) == ""


def test_sorted_t_cell_subsets_are_not_pbmc():
    ra = heuristic_parse(RA)
    for gse in ("GSE309906", "GSE279838"):
        summary, samples = _entry(gse)
        assert not any(tissue_matches(sample, ra.tissues) for sample in samples)
        assert "tissue" in rule_gate_ids(ra, summary, samples)
    for gse in ("GSE291978", "GSE266852"):
        _, samples = _entry(gse)
        assert all(tissue_matches(sample, ra.tissues) for sample in samples)


def test_repeated_preparations_of_one_donor_are_flagged():
    text = _reason(heuristic_parse(T2D), "GSE86468")
    assert "疑似同一供体的多份样本" in text
    assert "bulk sample type" in text
    assert "约 8 位供体" in text


def test_pediatric_controls_are_flagged():
    text = _reason(heuristic_parse(T2D), "GSE154126")
    assert "年龄段不匹配" in text
    assert "control" in text.split("年龄段不匹配")[1]


def test_reason_reports_independent_donors_when_keys_exist():
    text = _reason(heuristic_parse(RA), "GSE309906")
    assert "独立供体：case 3 / control 5。" in text


def test_cell_level_gsm_counts_are_not_presented_as_donors():
    spec = heuristic_parse(T2D)
    samples = []
    for index in range(60):
        disease = "T2D" if index < 30 else "non-diabetic"
        samples.append(
            {
                "gsm": f"GSM{index}",
                "title": f"islet cell {index}",
                "library_strategy": "RNA-Seq",
                "library_source": "transcriptomic",
                "characteristics": [
                    {"key": "tissue", "value": "Pancreatic islets", "raw": "tissue: Pancreatic islets"},
                    {"key": "cell type", "value": "Beta", "raw": "cell type: Beta"},
                    {"key": "disease", "value": disease, "raw": f"disease: {disease}"},
                ],
            }
        )
    summary = {"title": "islet single cells", "taxon": "Homo sapiens", "gdstype": "Expression profiling by high throughput sequencing"}
    rules = rule_judgements(spec, summary, samples)
    text = _annotate_reason("全部硬条件通过。", _Row(), summary, samples, spec=spec, merged=rules)
    assert "一个 GSM 多半是一个细胞" in text


def test_title_hint_ignores_donors_that_only_appear_in_treated_samples():
    text = _reason(heuristic_parse(RA), "GSE189136")
    assert "约 5 位个体" not in text


def test_title_count_hint_skips_one_cell_per_gsm_series():
    cells = [{"title": f"10th_C{i % 96}_S{i}"} for i in range(640)]
    assert _title_individual_count(cells) is None
    paired = [{"title": "RA1_S1"}, {"title": "RA1_S2"}, {"title": "RA2_S3"}, {"title": "RA2_S4"}]
    assert _title_individual_count(paired) == 2

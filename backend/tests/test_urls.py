from pathlib import Path

from app.core.urls import geo_bucket, series_soft_url
from app.exporters.excel import sanitize_cell


def test_urls_https_official():
    url = series_soft_url("GSE1000")
    assert url.startswith("https://ftp.ncbi.nlm.nih.gov/geo/series/GSE1nnn/GSE1000/soft/")
    assert geo_bucket("GSE1000") == "GSE1nnn"


def test_no_zero_for_unknown():
    assert sanitize_cell(None, numeric=True) is None
    assert sanitize_cell("", numeric=True) is None

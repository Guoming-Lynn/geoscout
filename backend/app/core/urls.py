from __future__ import annotations

from urllib.parse import urlparse

ALLOWED_FETCH_HOSTS = {
    "eutils.ncbi.nlm.nih.gov",
    "ftp.ncbi.nlm.nih.gov",
}

ALLOWED_LINK_HOSTS = ALLOWED_FETCH_HOSTS | {
    "www.ncbi.nlm.nih.gov",
    "ncbi.nlm.nih.gov",
}

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
FTP_HTTPS_BASE = "https://ftp.ncbi.nlm.nih.gov"
GEO_ACC_URL = "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi"


def geo_bucket(accession: str) -> str:
    """NCBI GEO FTP range directory: last three digits replaced with nnn."""
    prefix = "".join(ch for ch in accession if ch.isalpha()).upper()
    digits = "".join(ch for ch in accession if ch.isdigit())
    if len(digits) <= 3:
        return f"{prefix}nnn"
    return f"{prefix}{digits[:-3]}nnn"


def https_from_ftp(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme in {"ftp", "http"}:
        return f"https://{parsed.netloc}{parsed.path}"
    return url


def host_allowed(url: str, *, fetch: bool = True) -> bool:
    host = urlparse(url).hostname or ""
    allowed = ALLOWED_FETCH_HOSTS if fetch else ALLOWED_LINK_HOSTS
    return host.lower() in allowed


def series_soft_url(accession: str) -> str:
    acc = accession.upper()
    return f"{FTP_HTTPS_BASE}/geo/series/{geo_bucket(acc)}/{acc}/soft/{acc}_family.soft.gz"


def series_suppl_url(accession: str) -> str:
    acc = accession.upper()
    return f"{FTP_HTTPS_BASE}/geo/series/{geo_bucket(acc)}/{acc}/suppl/"


def accession_page(accession: str) -> str:
    return f"{GEO_ACC_URL}?acc={accession}"

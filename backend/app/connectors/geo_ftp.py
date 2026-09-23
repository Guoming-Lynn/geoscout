from __future__ import annotations

import logging
import asyncio
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.core.config import settings
from app.core.rate_limit import ncbi_limiter
from app.core.urls import ALLOWED_FETCH_HOSTS, host_allowed, https_from_ftp, series_soft_url, series_suppl_url

logger = logging.getLogger("geoscout.geo_ftp")


class GeoFetchError(Exception):
    def __init__(self, message: str, status_code: int | None = None, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


_RETRY_BACKOFF_S = (1.0, 3.0)


def _assert_allowed(url: str) -> str:
    normalized = https_from_ftp(url)
    parsed = urlparse(normalized)
    if parsed.scheme != "https":
        raise GeoFetchError("仅允许 HTTPS GEO 下载")
    if parsed.hostname not in ALLOWED_FETCH_HOSTS:
        raise GeoFetchError(f"拒绝非 GEO 官方域名: {parsed.hostname}")
    return normalized


class GeoFtpClient:
    def __init__(self, api_key: str | None = None, timeout: float | None = None) -> None:
        self.api_key = api_key
        self.timeout = timeout or settings.request_timeout_s

    async def fetch_bytes(self, url: str, *, max_bytes: int | None = None) -> tuple[bytes, str]:
        attempt = 0
        while True:
            try:
                return await self._fetch_once(url, max_bytes=max_bytes)
            except GeoFetchError as exc:
                if not exc.retryable or attempt >= len(_RETRY_BACKOFF_S):
                    raise
                logger.warning("GEO fetch retry %s after %s", attempt + 1, exc)
                await asyncio.sleep(_RETRY_BACKOFF_S[attempt])
                attempt += 1

    async def _fetch_once(self, url: str, *, max_bytes: int | None = None) -> tuple[bytes, str]:
        current = _assert_allowed(url)
        limit = max_bytes or settings.max_soft_bytes
        await ncbi_limiter.acquire(bool(self.api_key))
        try:
            async with asyncio.timeout(self.timeout):
                async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
                    for _ in range(4):
                        async with client.stream("GET", current) as response:
                            if response.status_code in {301, 302, 303, 307, 308}:
                                location = response.headers.get("location") or ""
                                current = _assert_allowed(urljoin(current, location))
                                continue
                            if response.status_code >= 400:
                                raise GeoFetchError(
                                    f"GEO 文件 HTTP {response.status_code}",
                                    response.status_code,
                                    retryable=response.status_code == 429 or response.status_code >= 500,
                                )
                            data = bytearray()
                            async for chunk in response.aiter_bytes():
                                if len(data) + len(chunk) > limit:
                                    raise GeoFetchError("文件超过下载上限，核验不完整")
                                data.extend(chunk)
                            return bytes(data), current
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise GeoFetchError("GEO 文件下载超时，核验不完整", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise GeoFetchError(f"GEO 文件网络错误: {type(exc).__name__}", retryable=True) from exc
        raise GeoFetchError("GEO 重定向次数过多")

    async def fetch_soft(self, accession: str) -> tuple[bytes, str]:
        url = series_soft_url(accession)
        return await self.fetch_bytes(url)

    async def list_suppl(self, accession: str) -> dict[str, Any]:
        url = series_suppl_url(accession)
        try:
            data, final_url = await self.fetch_bytes(url, max_bytes=1_000_000)
        except GeoFetchError as exc:
            return {
                "checked": True,
                "url": url,
                "status": "error",
                "error": str(exc),
                "names": [],
            }
        text = data.decode("utf-8", errors="replace")
        names = [line.strip() for line in text.splitlines() if accession.upper() in line.upper()]
        return {
            "checked": True,
            "url": final_url,
            "status": "ok",
            "names": names[:200],
            "raw_truncated": len(text) > 500_000,
        }


def classify_suppl_names(names: list[str]) -> dict[str, str]:
    """Filename-only matrix classes. Nothing here opens the file."""
    folded = [name.casefold() for name in names]

    def has(pred) -> bool:
        return any(pred(name) for name in folded)

    matrix = has(
        lambda name: any(token in name for token in (".h5ad", ".loom", ".mtx", ".h5")) or _counts_filename(name)
    )
    raw = has(lambda name: "raw.tar" in name)
    if matrix:
        return {
            "processed_data": "probable",
            "matrix_availability": "filename_only",
            "raw_data": "raw_tar" if raw else "unknown",
        }
    if raw:
        return {"processed_data": "unknown", "matrix_availability": "raw_archive", "raw_data": "raw_tar"}
    return {"processed_data": "unknown", "matrix_availability": "not_listed", "raw_data": "unknown"}


def _counts_filename(name: str) -> bool:
    if not any(token in name for token in ("count", "counts")):
        return False
    return any(ext in name for ext in (".csv", ".tsv", ".txt", ".xlsx"))

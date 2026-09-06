from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.core.config import settings
from app.core.rate_limit import ncbi_limiter
from app.core.urls import ALLOWED_FETCH_HOSTS, host_allowed, https_from_ftp, series_soft_url, series_suppl_url

logger = logging.getLogger("geoscout.geo_ftp")


class GeoFetchError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


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
        current = _assert_allowed(url)
        limit = max_bytes or settings.max_soft_bytes
        await ncbi_limiter.acquire(bool(self.api_key))
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
            for _ in range(4):
                response = await client.get(current)
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location") or ""
                    nxt = urljoin(current, location)
                    current = _assert_allowed(nxt)
                    continue
                if response.status_code >= 400:
                    raise GeoFetchError(f"GEO 文件 HTTP {response.status_code}", response.status_code)
                data = response.content
                if len(data) > limit:
                    raise GeoFetchError("文件超过下载上限，核验不完整")
                return data, current
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

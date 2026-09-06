from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.core.rate_limit import ncbi_limiter
from app.core.redact import redact_mapping, redact_text
from app.core.urls import EUTILS_BASE, host_allowed, https_from_ftp

logger = logging.getLogger("geoscout.ncbi")

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class NCBIError(Exception):
    def __init__(self, message: str, status_code: int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class NCBIClient:
    """NCBI E-utilities client for GEO DataSets (db=gds).

    Verified 2026-09-05 against live EInfo/ESearch/ESummary:
    - Base: https://eutils.ncbi.nlm.nih.gov/entrez/eutils/{esearch,esummary,einfo}.fcgi
    - db=gds
    - JSON via retmode=json
    - Fields: ETYP, ORGN, GTYP, ACCN (Accession also resolved)
    - ESummary entrytype in {GSE, GDS, GPL, GSM}; UID is not an accession
    """

    def __init__(
        self,
        *,
        tool: str | None = None,
        email: str | None = None,
        api_key: str | None = None,
        timeout: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.tool = (tool or settings.ncbi_tool or "GEOScout").replace(" ", "")
        self.email = (email if email is not None else settings.ncbi_email).replace(" ", "")
        self.api_key = api_key if api_key is not None else settings.ncbi_api_key
        self.timeout = timeout or settings.request_timeout_s
        self._transport = transport

    def _params(self, extra: dict[str, Any]) -> dict[str, Any]:
        params = {"tool": self.tool, **extra}
        if self.email:
            params["email"] = self.email
        if self.api_key:
            params["api_key"] = self.api_key
        return params

    async def _get_json(self, script: str, extra: dict[str, Any]) -> dict[str, Any]:
        url = f"{EUTILS_BASE}/{script}"
        params = self._params(extra)
        last_exc: Exception | None = None
        for attempt in range(5):
            await ncbi_limiter.acquire(bool(self.api_key))
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout,
                    follow_redirects=False,
                    transport=self._transport,
                ) as client:
                    response = await client.get(url, params=params)
            except httpx.TimeoutException as exc:
                last_exc = NCBIError("NCBI 请求超时", retryable=True)
                await asyncio.sleep(_backoff(attempt))
                logger.warning("ncbi timeout %s", redact_text(url))
                continue
            except httpx.HTTPError as exc:
                last_exc = NCBIError(f"NCBI 网络错误: {exc}", retryable=True)
                await asyncio.sleep(_backoff(attempt))
                continue

            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location", "")
                if not host_allowed(https_from_ftp(location)):
                    raise NCBIError("NCBI 重定向目标不在允许名单内")
                raise NCBIError("拒绝跟随非预期重定向", status_code=response.status_code)

            if response.status_code in {401, 403}:
                raise NCBIError("NCBI 拒绝访问，请检查 API Key 或身份配置", status_code=response.status_code)

            if response.status_code == 429:
                wait = _retry_after(response) or _backoff(attempt)
                logger.warning("ncbi 429, sleeping %.1fs", wait)
                await asyncio.sleep(wait)
                last_exc = NCBIError("NCBI 限流 429", status_code=429, retryable=True)
                continue

            if response.status_code in RETRYABLE_STATUS:
                last_exc = NCBIError(f"NCBI {response.status_code}", status_code=response.status_code, retryable=True)
                await asyncio.sleep(_backoff(attempt))
                continue

            if response.status_code >= 400:
                raise NCBIError(f"NCBI HTTP {response.status_code}", status_code=response.status_code)

            data = response.json()
            if not isinstance(data, dict):
                raise NCBIError("NCBI 返回了非 JSON 对象")
            return data

        raise last_exc or NCBIError("NCBI 请求失败")

    async def esearch(
        self,
        term: str,
        *,
        retstart: int = 0,
        retmax: int = 100,
    ) -> dict[str, Any]:
        data = await self._get_json(
            "esearch.fcgi",
            {
                "db": "gds",
                "term": term,
                "retmode": "json",
                "retstart": retstart,
                "retmax": retmax,
                "usehistory": "y",
            },
        )
        result = data.get("esearchresult") or {}
        return {
            "count": int(result.get("count") or 0),
            "retmax": int(result.get("retmax") or 0),
            "retstart": int(result.get("retstart") or 0),
            "idlist": list(result.get("idlist") or []),
            "querytranslation": result.get("querytranslation") or "",
            "translationset": result.get("translationset") or [],
            "webenv": result.get("webenv") or "",
            "querykey": result.get("querykey") or "",
            "raw": data,
        }

    async def esummary(self, ids: list[str]) -> list[dict[str, Any]]:
        if not ids:
            return []
        data = await self._get_json(
            "esummary.fcgi",
            {
                "db": "gds",
                "id": ",".join(ids),
                "retmode": "json",
            },
        )
        result = data.get("result") or {}
        uids = list(result.get("uids") or ids)
        records = []
        for uid in uids:
            rec = result.get(uid)
            if isinstance(rec, dict):
                rec = dict(rec)
                rec["uid"] = str(rec.get("uid") or uid)
                records.append(rec)
        return records


def _backoff(attempt: int) -> float:
    return min(20.0, (2**attempt) * 0.4) + random.uniform(0.05, 0.4)


def _retry_after(response: httpx.Response) -> float | None:
    header = response.headers.get("Retry-After")
    if not header:
        return None
    try:
        return max(float(header), 0.5)
    except ValueError:
        return None


def is_gse_record(record: dict[str, Any]) -> bool:
    entry = str(record.get("entrytype") or "").upper()
    acc = str(record.get("accession") or "").upper()
    return entry == "GSE" and acc.startswith("GSE")


def gse_from_summary(record: dict[str, Any]) -> str | None:
    if not is_gse_record(record):
        return None
    return str(record.get("accession")).upper()


def public_summary(record: dict[str, Any]) -> dict[str, Any]:
    pubmed = record.get("pubmedids") or []
    if isinstance(pubmed, str):
        pubmed = [pubmed] if pubmed else []
    samples = record.get("samples") or []
    sample_accessions = []
    if isinstance(samples, list):
        for item in samples:
            if isinstance(item, dict) and item.get("accession"):
                sample_accessions.append(item["accession"])
    return {
        "uid": str(record.get("uid") or ""),
        "accession": str(record.get("accession") or ""),
        "entrytype": str(record.get("entrytype") or ""),
        "title": record.get("title") or "",
        "summary": record.get("summary") or "",
        "taxon": record.get("taxon") or "",
        "gdstype": record.get("gdstype") or "",
        "gpl": str(record.get("gpl") or ""),
        "n_samples": _maybe_int(record.get("n_samples")),
        "pdat": record.get("pdat") or "",
        "pubmedids": [str(x) for x in pubmed],
        "suppfile": record.get("suppfile") or "",
        "ftplink": record.get("ftplink") or "",
        "bioproject": record.get("bioproject") or "",
        "gse_number": str(record.get("gse") or ""),
        "relations": record.get("relations") or [],
        "summary_sample_accessions": sample_accessions,
        "summary_sample_list_truncated": (
            _maybe_int(record.get("n_samples")) is not None
            and len(sample_accessions) < int(record.get("n_samples") or 0)
        ),
    }


def _maybe_int(value: Any) -> int | None:
    if value in (None, "", "NA"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def dump_redacted(payload: dict[str, Any]) -> str:
    return json.dumps(redact_mapping(payload), ensure_ascii=False)

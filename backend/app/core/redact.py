from __future__ import annotations

import re
from typing import Any

_KEY_NAMES = {
    "api_key",
    "apikey",
    "authorization",
    "token",
    "access_token",
    "internal_token",
    "ncbi_api_key",
    "x-internal-token",
}

_QUERY_KEY_RE = re.compile(r"([?&](?:api_key|token|access_token|key)=)([^&]+)", re.I)
_BEARER_RE = re.compile(r"(Bearer\s+)(\S+)", re.I)


def redact_text(value: str | None) -> str:
    if not value:
        return ""
    text = _QUERY_KEY_RE.sub(r"\1***", value)
    text = _BEARER_RE.sub(r"\1***", text)
    return text


def redact_mapping(data: Any) -> Any:
    if isinstance(data, dict):
        out = {}
        for key, val in data.items():
            if str(key).lower() in _KEY_NAMES or "api_key" in str(key).lower():
                out[key] = "***"
            else:
                out[key] = redact_mapping(val)
        return out
    if isinstance(data, list):
        return [redact_mapping(item) for item in data]
    if isinstance(data, str):
        return redact_text(data)
    return data


def contains_secret(text: str | None, secret: str | None) -> bool:
    if not text or not secret or len(secret) < 8:
        return False
    return secret in text

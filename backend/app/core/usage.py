from __future__ import annotations

from typing import Any


def add_usage(current: dict[str, Any], usage: dict[str, Any]) -> dict[str, Any]:
    result = dict(current)
    for field in ("prompt_tokens", "completion_tokens", "request_count", "missing_usage_requests"):
        result[field] = int(result.get(field) or 0) + int(usage.get(field) or 0)
    result["total_tokens"] = result["prompt_tokens"] + result["completion_tokens"]
    result["estimated"] = bool(current.get("estimated") or usage.get("estimated"))
    return result

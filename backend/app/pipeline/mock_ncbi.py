from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures"


class MockNCBIClient:
    """Deterministic NCBI stand-in. Used only when GEOSCOUT_NCBI_MODE=mock or explicit demo."""

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self.tool = "GEOScout"
        self.email = ""
        self.api_key = ""

    async def esearch(self, term: str, *, retstart: int = 0, retmax: int = 100) -> dict[str, Any]:
        payload = json.loads((FIXTURE_DIR / "esearch_gds.json").read_text(encoding="utf-8"))
        ids = list(payload["esearchresult"]["idlist"])
        sliced = ids[retstart : retstart + retmax]
        return {
            "count": int(payload["esearchresult"]["count"]),
            "retmax": len(sliced),
            "retstart": retstart,
            "idlist": sliced,
            "querytranslation": payload["esearchresult"].get("querytranslation") or term,
            "translationset": payload["esearchresult"].get("translationset") or [],
            "webenv": "",
            "querykey": "",
            "raw": payload,
        }

    async def esummary(self, ids: list[str]) -> list[dict[str, Any]]:
        payload = json.loads((FIXTURE_DIR / "esummary_gds.json").read_text(encoding="utf-8"))
        result = payload["result"]
        out = []
        for uid in ids:
            rec = result.get(uid)
            if rec:
                rec = dict(rec)
                rec["uid"] = uid
                out.append(rec)
        return out

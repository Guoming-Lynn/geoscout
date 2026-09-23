"""Export deep-reviewed samples from the 2026-09-23 rerun for offline tests.

Reads the local SQLite file only. Does not use network or API keys.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "flash-rerun-20260923" / "geoscout.db"
OUT = ROOT / "backend" / "tests" / "fixtures" / "flash_round2_samples.json"
FULL = (
    "GSE86468",
    "GSE164416",
    "GSE291978",
    "GSE189136",
    "GSE309036",
    "GSE163605",
    "GSE317746",
    "GSE153855",
    "GSE266852",
)
PARTIAL = "GSE81608"
SUMMARY_KEYS = ("title", "summary", "overall_design", "gdstype", "taxon", "n_samples")


def _load(raw: str | None, default):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def _sample(row: sqlite3.Row) -> dict:
    attrs = _load(row["attrs_json"], {})
    protocol = str(attrs.get("protocol") or "")
    if len(protocol) > 1500:
        protocol = protocol[:1500]
    return {
        "gsm": row["gsm"],
        "title": row["title"] or "",
        "organism": row["organism"] or "",
        "source_name": row["source_name"] or "",
        "donor_key": row["donor_key"],
        "library_strategy": attrs.get("library_strategy") or row["library_strategy"] or "",
        "library_source": attrs.get("library_source") or "",
        "protocol": protocol,
        "protocol_fields": attrs.get("protocol_fields") or {},
        "characteristics": _load(row["characteristics_json"], []),
        "coverage_incomplete": bool(row["coverage_incomplete"]),
    }


def _summary(row: sqlite3.Row) -> dict:
    blob = _load(row["summary_json"], {})
    out = {key: blob.get(key) or "" for key in SUMMARY_KEYS}
    out["title"] = out["title"] or row["title"] or ""
    out["gdstype"] = out["gdstype"] or row["gdstype"] or ""
    out["taxon"] = out["taxon"] or row["taxon"] or ""
    if row["n_samples"] is not None:
        out["n_samples"] = row["n_samples"]
    return out


def main() -> None:
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    payload: dict[str, dict] = {}
    for gse in (*FULL, PARTIAL):
        dataset = db.execute("select * from datasets where gse=?", (gse,)).fetchone()
        if dataset is None:
            raise SystemExit(f"missing dataset {gse}")
        rows = db.execute("select * from samples where gse=? order by gsm", (gse,)).fetchall()
        if gse == PARTIAL:
            rows = list(rows[:60]) + list(rows[-60:])
        payload[gse] = {"summary": _summary(dataset), "samples": [_sample(row) for row in rows]}
        print(gse, len(payload[gse]["samples"]))
    OUT.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print("wrote", OUT, OUT.stat().st_size)


if __name__ == "__main__":
    main()

"""Export samples from the 2026-09-24 fifth rerun for offline tests.

Reads the local SQLite file only. Does not use network or API keys.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from export_round2_fixtures import _sample, _summary

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "flash-round5-20260924" / "geoscout.db"
OUT = ROOT / "backend" / "tests" / "fixtures" / "flash_round5_samples.json"
GSES = (
    "GSE334803",
    "GSE123141",
    "GSE277964",
    "GSE224758",
    "GSE235236",
    "GSE266325",
    "GSE222070",
    "GSE276170",
    "GSE102746",
    "GSE300475",
    "GSE313152",
    "GSE252950",
    "GSE338456",
    "GSE309616",
    "GSE303201",
    "GSE298343",
    "GSE271307",
    "GSE193677",
)
LIMIT = {"GSE193677": 300}


def main() -> None:
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    payload: dict[str, dict] = {}
    for gse in GSES:
        dataset = db.execute("select * from datasets where gse=?", (gse,)).fetchone()
        if dataset is None:
            raise SystemExit(f"missing dataset {gse}")
        rows = db.execute("select * from samples where gse=? order by gsm", (gse,)).fetchall()
        truncated = False
        if gse in LIMIT:
            rows = list(rows[: LIMIT[gse]])
            truncated = True
        entry = {"summary": _summary(dataset), "samples": [_sample(row) for row in rows]}
        if truncated:
            entry["truncated_fixture"] = True
        payload[gse] = entry
        print(gse, len(entry["samples"]))
    OUT.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print("wrote", OUT, OUT.stat().st_size)


if __name__ == "__main__":
    main()

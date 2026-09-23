"""Export samples from the 2026-09-23 third rerun for offline tests.

Reads the local SQLite file only. Does not use network or API keys.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from export_round2_fixtures import _sample, _summary

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "flash-round3-20260923" / "geoscout.db"
OUT = ROOT / "backend" / "tests" / "fixtures" / "flash_round3_samples.json"
FULL = ("GSE318560", "GSE309906", "GSE279838")
PER_DONOR = {"GSE154126": 3}


def main() -> None:
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    payload: dict[str, dict] = {}
    for gse in (*FULL, *PER_DONOR):
        dataset = db.execute("select * from datasets where gse=?", (gse,)).fetchone()
        if dataset is None:
            raise SystemExit(f"missing dataset {gse}")
        rows = db.execute("select * from samples where gse=? order by gsm", (gse,)).fetchall()
        if gse in PER_DONOR:
            kept: dict[str, list[sqlite3.Row]] = {}
            for row in rows:
                bucket = kept.setdefault(row["source_name"] or "", [])
                if len(bucket) < PER_DONOR[gse]:
                    bucket.append(row)
            rows = [row for bucket in kept.values() for row in bucket]
        payload[gse] = {"summary": _summary(dataset), "samples": [_sample(row) for row in rows]}
        print(gse, len(payload[gse]["samples"]))
    OUT.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print("wrote", OUT, OUT.stat().st_size)


if __name__ == "__main__":
    main()

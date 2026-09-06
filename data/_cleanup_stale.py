import sqlite3
from datetime import datetime, timezone

db = r"D:\vesscular data\geoscout\data\geoscout.db"
con = sqlite3.connect(db)
keep_session = "p7YgisMopAsN5bPDzEP0s6nB"
keep_runs = [
    r[0]
    for r in con.execute(
        "SELECT r.id FROM runs r JOIN projects p ON p.id=r.project_id WHERE p.name LIKE 'ds-retest%'"
    )
]
print("keep_runs", keep_runs)
q = ",".join("?" * len(keep_runs)) if keep_runs else "''"
stale_runs = [
    r[0]
    for r in con.execute(
        f"""
        SELECT id FROM runs
        WHERE status IN ('queued','running','waiting_for_credentials','pausing','paused')
          AND id NOT IN ({q or "''"})
        """,
        keep_runs,
    )
]
print("stale_run_count", len(stale_runs))
now = datetime.now(timezone.utc).isoformat()
if stale_runs:
    ph = ",".join("?" * len(stale_runs))
    con.execute(
        f"UPDATE jobs SET status='cancelled' WHERE run_id IN ({ph}) AND status IN ('queued','leased')",
        stale_runs,
    )
    con.execute(
        f"""UPDATE runs SET status='cancelled', stop_reason='retest cleanup after API restart',
            finished_at=?, pause_requested=0, cancel_requested=1
            WHERE id IN ({ph})""",
        [now, *stale_runs],
    )
    con.commit()
print("queued remaining", con.execute("SELECT status, step, count(*) FROM jobs WHERE status IN ('queued','leased') GROUP BY status, step").fetchall())
print("active remaining", con.execute("SELECT id, status, stage, session_id FROM runs WHERE status IN ('queued','running','waiting_for_credentials')").fetchall())
con.close()

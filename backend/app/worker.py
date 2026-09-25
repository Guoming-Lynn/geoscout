from __future__ import annotations

import asyncio
import logging
import os
import socket
import sys
from contextlib import suppress
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path and not getattr(sys, "frozen", False):
    sys.path.insert(0, str(ROOT))

from app.db.models import Job
from app.core.config import settings
from app.db.session import SessionLocal, init_db
from app.pipeline.engine import Engine
from app.pipeline.repo import claim_job, heartbeat

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("geoscout.worker")
WORKER_ID = f"{socket.gethostname()}-{os.getpid()}"


async def _run_one() -> None:
    async with SessionLocal() as session:
        job = await claim_job(session, WORKER_ID, settings.job_lease_s)
        if job is None:
            await session.commit()
            await asyncio.sleep(0.4)
            return
        await session.commit()
        job_id = job.id
        logger.info("claimed %s %s", job.step, job.run_id)
    stop = asyncio.Event()

    async def renew() -> None:
        interval = max(5, settings.job_lease_s / 3)
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
                return
            except TimeoutError:
                pass
            async with SessionLocal() as beat:
                current = await beat.get(Job, job_id)
                if current is None or current.status != "leased" or current.worker_id != WORKER_ID:
                    return
                await heartbeat(beat, current, settings.job_lease_s)
                await beat.commit()

    renew_task = asyncio.create_task(renew())
    try:
        async with SessionLocal() as work:
            job2 = await work.get(Job, job_id)
            if job2 is None:
                return
            await heartbeat(work, job2, settings.job_lease_s)
            engine = Engine(work, job2, WORKER_ID)
            await engine.run()
            await work.commit()
    finally:
        stop.set()
        renew_task.cancel()
        # A stuck lease renewal must not freeze the next claim.
        with suppress(asyncio.CancelledError, TimeoutError, Exception):
            await asyncio.wait_for(renew_task, timeout=5)


async def loop() -> None:
    await init_db()
    logger.info("worker %s started", WORKER_ID)
    while True:
        try:
            await _run_one()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("worker loop error; continuing")
            await asyncio.sleep(1)


def run() -> None:
    asyncio.run(loop())


if __name__ == "__main__":
    run()

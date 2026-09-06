from __future__ import annotations

import asyncio
import logging
import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.models import Job
from app.core.config import settings
from app.db.session import SessionLocal, init_db
from app.pipeline.engine import Engine
from app.pipeline.repo import claim_job, heartbeat

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("geoscout.worker")
WORKER_ID = f"{socket.gethostname()}-{os.getpid()}"


async def loop() -> None:
    await init_db()
    logger.info("worker %s started", WORKER_ID)
    while True:
        async with SessionLocal() as session:
            job = await claim_job(session, WORKER_ID, settings.job_lease_s)
            if job is None:
                await session.commit()
                await asyncio.sleep(0.4)
                continue
            await session.commit()
            try:
                async with SessionLocal() as work:
                    job2 = await work.get(Job, job.id)
                    if job2 is None:
                        continue
                    await heartbeat(work, job2, settings.job_lease_s)
                    engine = Engine(work, job2, WORKER_ID)
                    await engine.run()
                    await work.commit()
            except Exception:
                logger.exception("worker job crashed")
                await asyncio.sleep(1)


def run() -> None:
    asyncio.run(loop())


if __name__ == "__main__":
    run()

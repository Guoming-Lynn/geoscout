from __future__ import annotations

import asyncio
import random
import time
from collections import deque


class SharedRateLimiter:
    """Process-wide limiter for NCBI E-utilities.

    NCBI policy (verified 2026-09-05 from NCBI Insights / E-utilities help):
    without api_key: <= 3 requests / second / IP
    with api_key: <= 10 requests / second / key
    Large jobs should run evenings/weekends US Eastern time.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._stamps: deque[float] = deque()

    def max_rate(self, has_api_key: bool) -> int:
        return 10 if has_api_key else 3

    async def acquire(self, has_api_key: bool) -> None:
        limit = self.max_rate(has_api_key)
        window = 1.05
        while True:
            async with self._lock:
                now = time.monotonic()
                while self._stamps and now - self._stamps[0] > window:
                    self._stamps.popleft()
                if len(self._stamps) < limit:
                    self._stamps.append(now)
                    return
                wait = window - (now - self._stamps[0]) + random.uniform(0.02, 0.12)
            await asyncio.sleep(max(wait, 0.05))


ncbi_limiter = SharedRateLimiter()

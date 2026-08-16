"""
In-process rolling-window rate limiter.

PseudoGram allows 10 requests per rolling 60s. Under a 500-events/10s
burst we cannot fire requests as fast as jobs are created -- we must
throttle ourselves proactively, not just react to 429s (reacting only
to 429 would mean we've already wasted a request and possibly tripped
a harsher penalty).

Limitation (documented again in FAILURES.md): this is per-process
in-memory state. If Render ever runs more than one instance of this
service, each instance would think it has its own 10/60s budget and
the *combined* traffic could exceed PseudoGram's real limit. For a
single Render instance (the default, and what we deploy) this is
correct.
"""
import asyncio
import time
from collections import deque


class RollingWindowRateLimiter:
    def __init__(self, max_calls: int, window_seconds: float = 60.0):
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                while self._timestamps and now - self._timestamps[0] >= self.window_seconds:
                    self._timestamps.popleft()
                if len(self._timestamps) < self.max_calls:
                    self._timestamps.append(now)
                    return
                sleep_for = self.window_seconds - (now - self._timestamps[0]) + 0.01
            await asyncio.sleep(max(sleep_for, 0.01))

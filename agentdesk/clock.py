"""Injectable clock. Every time read in runner, credfile, and collectors goes through Clock."""

from __future__ import annotations

import time


class Clock:
    """Wall and monotonic time plus sleep. Production default."""

    def now(self) -> float:
        return time.time()

    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)

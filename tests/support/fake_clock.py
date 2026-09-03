"""Test clock. sleep() advances now and monotonic and wakes a select pipe."""

from __future__ import annotations

import os

from agentdesk.clock import Clock


class FakeClock(Clock):
    """Test clock. sleep() advances now and monotonic and wakes a select pipe."""

    def __init__(self, now: float = 0.0, monotonic: float = 0.0):
        self._now = float(now)
        self._mono = float(monotonic)
        self.wake_fd = None

    def now(self) -> float:
        return self._now

    def monotonic(self) -> float:
        return self._mono

    def sleep(self, seconds: float) -> None:
        self.advance(seconds)

    def advance(self, seconds: float) -> None:
        seconds = float(seconds)
        self._now += seconds
        self._mono += seconds
        if self.wake_fd is not None:
            try:
                os.write(self.wake_fd, b"\0")
            except OSError:
                pass

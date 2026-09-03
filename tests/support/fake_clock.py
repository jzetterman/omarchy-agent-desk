"""Re-export Clock types so tests can import from the support package."""

from agentdesk.clock import Clock, FakeClock

__all__ = ["Clock", "FakeClock"]

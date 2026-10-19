from __future__ import annotations


class VirtualTime:
    """A monotonic clock the test moves: `sleep` advances it and so does a transport that takes time (`took`), so
    polling is exercised without waiting, and what it costs in (virtual) seconds is exact."""

    def __init__(self) -> None:
        self.now, self.sleeps = 0.0, []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def took(self, seconds: float, timeout: float) -> bool:
        """Spend a request's time, up to its timeout: True when the transport answered inside it, False when it timed out."""
        self.now += min(seconds, timeout)
        return seconds <= timeout

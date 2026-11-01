"""In-process sliding-window rate limiter (prototype extension)."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, limit_per_minute: int, *, window_seconds: float = 60.0) -> None:
        self.limit = max(0, limit_per_minute)
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.limit > 0

    def check(self, key: str) -> int | None:
        """Return ``Retry-After`` seconds when limited, otherwise ``None``."""
        if not self.enabled:
            return None
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) < self.limit:
                events.append(now)
                return None
            return max(1, int(self.window_seconds - (now - events[0])) + 1)

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


__all__ = ["RateLimiter"]

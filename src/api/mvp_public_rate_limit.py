"""Bounded process-local burst admission for public widget requests."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from uuid import UUID

import anyio


@dataclass(frozen=True, slots=True)
class BurstDecision:
    """Deterministic sliding-window decision."""

    allowed: bool
    retry_after: int | None = None


class BurstRateLimiter:
    """Bound per-publication and direct-peer-IP windows in process memory."""

    def __init__(self, *, limit: int, window_seconds: int, capacity: int) -> None:
        if limit < 1 or window_seconds < 1 or capacity < 1:
            raise ValueError
        self._limit = limit
        self._window_seconds = window_seconds
        self._capacity = capacity
        self._windows: dict[tuple[UUID, str], list[float]] = {}
        self._lock = anyio.Lock()

    async def admit(
        self, publication_id: UUID, client_ip: str, now: float
    ) -> BurstDecision:
        """Admit one attempt and evict inactive keys under one async lock."""
        key = (publication_id, client_ip)
        cutoff = now - self._window_seconds
        async with self._lock:
            self._evict(cutoff, key)
            timestamps = [
                timestamp
                for timestamp in self._windows.get(key, [])
                if timestamp > cutoff
            ]
            if len(timestamps) >= self._limit:
                self._windows[key] = timestamps
                return BurstDecision(
                    False,
                    max(1, ceil(timestamps[0] + self._window_seconds - now)),
                )
            timestamps.append(now)
            self._windows[key] = timestamps
        return BurstDecision(True)

    def _evict(self, cutoff: float, current: tuple[UUID, str]) -> None:
        stale = [
            key
            for key, values in self._windows.items()
            if not values or values[-1] <= cutoff
        ]
        for key in stale:
            del self._windows[key]
        if current not in self._windows and len(self._windows) >= self._capacity:
            oldest = min(self._windows, key=lambda key: self._windows[key][-1])
            del self._windows[oldest]

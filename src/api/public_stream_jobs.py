"""Bounded widget-only live execution cancellation registry."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import anyio


class PublicStreamConflictError(RuntimeError):
    """Reject a second live execution for the same public session."""


class PublicStreamCapacityError(RuntimeError):
    """Reject work beyond the bounded process-local public capacity."""


@dataclass(frozen=True, slots=True)
class PublicStreamKey:
    """Namespace jobs independently from all private session registries."""

    publication_id: UUID
    session_id: UUID

    @property
    def graph_session_id(self) -> str:
        """Return a public-only graph thread identifier."""
        return f"widget:{self.publication_id.hex}:{self.session_id.hex}"


@dataclass(frozen=True, slots=True)
class PublicStreamLease:
    """One live cancellation scope owned by a public request."""

    key: PublicStreamKey
    cancel_scope: anyio.CancelScope


class PublicStreamJobRegistry:
    """Track only in-process public streams and retain no replay or history."""

    def __init__(self, capacity: int = 10) -> None:
        if capacity < 1:
            raise PublicStreamCapacityError
        self._capacity = capacity
        self._leases: dict[PublicStreamKey, PublicStreamLease] = {}
        self._lock = anyio.Lock()

    async def acquire(self, key: PublicStreamKey) -> PublicStreamLease:
        """Reserve one widget-only session before graph execution begins."""
        async with self._lock:
            if key in self._leases:
                raise PublicStreamConflictError
            if len(self._leases) >= self._capacity:
                raise PublicStreamCapacityError
            lease = PublicStreamLease(key, anyio.CancelScope())
            self._leases[key] = lease
            return lease

    async def cancel(self, key: PublicStreamKey) -> bool:
        """Cancel one exact public job without consulting private registries."""
        async with self._lock:
            lease = self._leases.get(key)
        if lease is None:
            return False
        lease.cancel_scope.cancel()
        return True

    async def release(self, lease: PublicStreamLease) -> None:
        """Remove one completed lease idempotently."""
        async with self._lock:
            if self._leases.get(lease.key) is lease:
                self._leases.pop(lease.key)

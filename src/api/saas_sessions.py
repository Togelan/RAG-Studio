"""Server-owned SaaS sessions and trusted workspace membership contracts."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol
from uuid import UUID

import anyio

from src.api.saas_security import BffSessionHandle


class WorkspaceRole(StrEnum):
    """Launch roles authorized by FR-013."""

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


@dataclass(frozen=True, slots=True)
class Membership:
    """An active user membership resolved from the tenant authority."""

    workspace_id: UUID
    role: WorkspaceRole


class MembershipResolver(Protocol):
    """Resolve current active membership on every tenant request."""

    async def resolve(self, user_id: UUID, workspace_id: UUID) -> Membership | None: ...


@dataclass(frozen=True, slots=True)
class BffSession:
    """Provider credentials retained only by the BFF."""

    handle: BffSessionHandle
    user_id: UUID
    email: str
    access_token: str
    refresh_token: str
    expires_at: float
    active_workspace_id: UUID | None = None


class BffSessionStore:
    """Bounded in-process store for opaque browser session handles."""

    def __init__(self) -> None:
        self._sessions: dict[BffSessionHandle, BffSession] = {}
        self._lock = anyio.Lock()

    async def create(
        self,
        *,
        user_id: UUID,
        email: str,
        access_token: str,
        refresh_token: str,
        lifetime_seconds: int,
    ) -> BffSession:
        """Create an unguessable handle with a bounded lifetime."""
        session = BffSession(
            handle=BffSessionHandle(secrets.token_urlsafe(32)),
            user_id=user_id,
            email=email,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=time.time() + lifetime_seconds,
        )
        async with self._lock:
            self._sessions[session.handle] = session
        return session

    async def get(self, handle: BffSessionHandle) -> BffSession | None:
        """Return a live session without extending its lifetime."""
        async with self._lock:
            session = self._sessions.get(handle)
            if session is None:
                return None
            if session.expires_at <= time.time():
                self._sessions.pop(handle, None)
                return None
            return session

    async def rotate(
        self,
        old_handle: BffSessionHandle,
        *,
        user_id: UUID,
        email: str,
        access_token: str,
        refresh_token: str,
        lifetime_seconds: int,
    ) -> BffSession | None:
        """Replace a session handle atomically after provider refresh."""
        replacement = BffSession(
            handle=BffSessionHandle(secrets.token_urlsafe(32)),
            user_id=user_id,
            email=email,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=time.time() + lifetime_seconds,
        )
        async with self._lock:
            current = self._sessions.pop(old_handle, None)
            if current is None:
                return None
            replacement = replace(
                replacement,
                active_workspace_id=current.active_workspace_id,
            )
            self._sessions[replacement.handle] = replacement
        return replacement

    async def select_workspace(
        self,
        handle: BffSessionHandle,
        workspace_id: UUID | None,
    ) -> BffSession | None:
        """Update only the server-owned workspace selection."""
        async with self._lock:
            current = self._sessions.get(handle)
            if current is None:
                return None
            updated = replace(current, active_workspace_id=workspace_id)
            self._sessions[handle] = updated
            return updated

    async def delete(self, handle: BffSessionHandle) -> BffSession | None:
        """Invalidate a local browser session."""
        async with self._lock:
            return self._sessions.pop(handle, None)


@dataclass(frozen=True, slots=True)
class DenyAllMembershipResolver:
    """Fail-closed resolver until workspace persistence is wired by Task 5."""

    async def resolve(self, user_id: UUID, workspace_id: UUID) -> Membership | None:
        del user_id, workspace_id
        return None

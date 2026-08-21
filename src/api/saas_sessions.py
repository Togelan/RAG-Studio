"""Server-owned SaaS sessions and trusted workspace membership contracts."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4

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
    refresh_expires_at: float = 0.0
    rotation_version: int = 1
    active_account_id: UUID | None = None
    active_workspace_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class SessionRefreshLease:
    """Exclusive bounded permission to rotate one session version."""

    session: BffSession
    lease_id: UUID
    rotation_version: int


class BffSessionStore:
    """Bounded in-process store for opaque browser session handles."""

    def __init__(self) -> None:
        self._sessions: dict[BffSessionHandle, BffSession] = {}
        self._refresh_leases: dict[BffSessionHandle, tuple[UUID, float, int]] = {}
        self._lock = anyio.Lock()

    async def create(
        self,
        *,
        user_id: UUID,
        email: str,
        access_token: str,
        refresh_token: str,
        lifetime_seconds: int,
        refresh_lifetime_seconds: int | None = None,
    ) -> BffSession:
        """Create an unguessable handle with a bounded lifetime."""
        refresh_lifetime = refresh_lifetime_seconds or lifetime_seconds
        session = BffSession(
            handle=BffSessionHandle(secrets.token_urlsafe(32)),
            user_id=user_id,
            email=email,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=time.time() + lifetime_seconds,
            refresh_expires_at=time.time() + refresh_lifetime,
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
            if session.refresh_expires_at <= time.time():
                self._sessions.pop(handle, None)
                self._refresh_leases.pop(handle, None)
                return None
            return session

    async def begin_refresh(
        self, handle: BffSessionHandle
    ) -> SessionRefreshLease | None:
        """Claim a bounded refresh lease before contacting the identity provider."""
        async with self._lock:
            session = self._sessions.get(handle)
            if session is None or session.refresh_expires_at <= time.time():
                return None
            current = self._refresh_leases.get(handle)
            if current is not None and current[1] > time.time():
                return None
            lease_id = uuid4()
            self._refresh_leases[handle] = (
                lease_id,
                time.time() + 15,
                session.rotation_version,
            )
            return SessionRefreshLease(session, lease_id, session.rotation_version)

    async def rotate(
        self,
        old_handle: BffSessionHandle,
        *,
        user_id: UUID,
        email: str,
        access_token: str,
        refresh_token: str,
        lifetime_seconds: int,
        refresh_lifetime_seconds: int | None = None,
        lease: SessionRefreshLease | None = None,
    ) -> BffSession | None:
        """Replace a session handle atomically after provider refresh."""
        claimed = lease or await self.begin_refresh(old_handle)
        if claimed is None:
            return None
        refresh_lifetime = refresh_lifetime_seconds or lifetime_seconds
        replacement = BffSession(
            handle=BffSessionHandle(secrets.token_urlsafe(32)),
            user_id=user_id,
            email=email,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=time.time() + lifetime_seconds,
            refresh_expires_at=time.time() + refresh_lifetime,
            rotation_version=claimed.rotation_version + 1,
        )
        async with self._lock:
            current = self._sessions.get(old_handle)
            current_lease = self._refresh_leases.get(old_handle)
            if (
                current is None
                or current_lease is None
                or current_lease[0] != claimed.lease_id
                or current.rotation_version != claimed.rotation_version
            ):
                return None
            replacement = replace(
                replacement,
                active_account_id=current.active_account_id,
                active_workspace_id=current.active_workspace_id,
            )
            self._sessions.pop(old_handle, None)
            self._refresh_leases.pop(old_handle, None)
            self._sessions[replacement.handle] = replacement
        return replacement

    async def select_account(
        self,
        handle: BffSessionHandle,
        account_id: UUID | None,
    ) -> BffSession | None:
        """Update the server-owned Account selection and clear its Workspace."""
        async with self._lock:
            current = self._sessions.get(handle)
            if current is None:
                return None
            updated = replace(
                current,
                active_account_id=account_id,
                active_workspace_id=None,
            )
            self._sessions[handle] = updated
            return updated

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
            self._refresh_leases.pop(handle, None)
            return self._sessions.pop(handle, None)

    async def cleanup_expired(self, *, limit: int = 100) -> int:
        """Remove at most ``limit`` expired or revoked in-process sessions."""
        async with self._lock:
            expired = [
                handle
                for handle, session in self._sessions.items()
                if session.refresh_expires_at <= time.time()
            ][:limit]
            for handle in expired:
                self._sessions.pop(handle, None)
                self._refresh_leases.pop(handle, None)
            return len(expired)


@dataclass(frozen=True, slots=True)
class DenyAllMembershipResolver:
    """Fail-closed resolver until workspace persistence is wired by Task 5."""

    async def resolve(self, user_id: UUID, workspace_id: UUID) -> Membership | None:
        del user_id, workspace_id
        return None

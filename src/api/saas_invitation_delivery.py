"""Invitation token issuance and SMTP delivery for the trusted BFF."""

from __future__ import annotations

import hashlib
import hmac
import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol
from urllib.parse import quote
from uuid import UUID

import anyio
from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
)

from src.api.saas_workspace_models import (
    InvitationCreation,
    WorkspaceErrorCode,
    WorkspaceOperationError,
)


@dataclass(frozen=True, slots=True)
class InvitationMessage:
    """One local-inbox delivery without audit or response exposure."""

    email: str
    token: str
    workspace_id: UUID


class InvitationMailer(Protocol):
    """Deliver one invitation bearer token outside persistent audit data."""

    async def send(self, message: InvitationMessage) -> None: ...


@dataclass(frozen=True, slots=True)
class InvitationTokenIssuer:
    """Derive retry-stable opaque invitation tokens with domain separation."""

    secret: SecretStr

    def issue(self, command: InvitationCreation) -> str:
        """Return the same unguessable token for one actor request key."""
        payload = (
            f"rag-studio:invite:v1:{command.actor.workspace_id}:"
            f"{command.actor.user_id}:{command.idempotency_key}"
        )
        return hmac.new(
            self.secret.get_secret_value().encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()


class _DeliveryEnvironment(BaseModel):
    model_config = ConfigDict(frozen=True)

    host: str = Field(min_length=1)
    port: int = Field(gt=0, le=65535)
    site_url: AnyHttpUrl
    starttls: bool = False
    username: str | None = None
    password: SecretStr | None = None


@dataclass(frozen=True, slots=True)
class InvitationDeliveryConfiguration:
    """Environment-derived SMTP delivery configuration."""

    host: str
    port: int
    site_url: str
    starttls: bool
    username: str | None
    password: SecretStr | None


def load_invitation_delivery_configuration() -> InvitationDeliveryConfiguration | None:
    """Parse optional SMTP configuration without reading a dotenv file."""
    host = os.getenv("RAG_STUDIO_INVITATION_SMTP_HOST")
    site_url = os.getenv("RAG_STUDIO_INVITATION_SITE_URL")
    if host is None and site_url is None:
        return None
    try:
        parsed = _DeliveryEnvironment.model_validate(
            {
                "host": host,
                "port": os.getenv("RAG_STUDIO_INVITATION_SMTP_PORT", "25"),
                "site_url": site_url,
                "starttls": os.getenv("RAG_STUDIO_INVITATION_SMTP_STARTTLS", "false"),
                "username": os.getenv("RAG_STUDIO_INVITATION_SMTP_USERNAME"),
                "password": os.getenv("RAG_STUDIO_INVITATION_SMTP_PASSWORD"),
            }
        )
    except ValidationError:
        return None
    return InvitationDeliveryConfiguration(
        host=parsed.host,
        port=parsed.port,
        site_url=str(parsed.site_url).rstrip("/"),
        starttls=parsed.starttls,
        username=parsed.username,
        password=parsed.password,
    )


@dataclass(frozen=True, slots=True)
class SmtpInvitationMailer:
    """Bounded SMTP adapter suitable for local inbox or configured production SMTP."""

    configuration: InvitationDeliveryConfiguration

    async def send(self, message: InvitationMessage) -> None:
        """Send one link while keeping the bearer token out of logs and errors."""
        try:
            await anyio.to_thread.run_sync(self._send_sync, message)
        except OSError, smtplib.SMTPException:
            raise WorkspaceOperationError(WorkspaceErrorCode.UNAVAILABLE) from None

    def _send_sync(self, message: InvitationMessage) -> None:
        email = EmailMessage()
        email["From"] = "noreply@rag-studio.local"
        email["To"] = message.email
        email["Subject"] = "RAG-Studio workspace invitation"
        token = quote(message.token, safe="")
        email.set_content(
            f"{self.configuration.site_url}/saas/invitations/accept?token={token}"
        )
        with smtplib.SMTP(
            self.configuration.host, self.configuration.port, timeout=5.0
        ) as client:
            if self.configuration.starttls:
                client.starttls(context=ssl.create_default_context())
            if self.configuration.username is not None:
                password = self.configuration.password
                if password is None:
                    raise smtplib.SMTPAuthenticationError(535, b"authentication failed")
                client.login(self.configuration.username, password.get_secret_value())
            client.send_message(email)


@dataclass(frozen=True, slots=True)
class UnavailableInvitationMailer:
    """Fail closed when SMTP delivery is not configured."""

    async def send(self, message: InvitationMessage) -> None:
        del message
        raise WorkspaceOperationError(WorkspaceErrorCode.UNAVAILABLE)

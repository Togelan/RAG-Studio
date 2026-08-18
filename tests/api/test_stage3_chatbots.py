from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from src.api import saas_chat_models
from src.api.routes.saas_chat import create_saas_chat_router
from src.api.routes.saas_chatbots import create_saas_chatbots_router
from src.api.saas_auth_context import AuthContext
from src.api.saas_chat_models import (
    ChatbotConfiguration,
    ChatbotExecutionConfiguration,
    ChatbotUnavailableError,
    ExecutionChannel,
    SupportedLocale,
)
from src.api.saas_chat_persistence import TenantChatStore
from src.api.saas_chat_runtime import TenantChatRuntime
from src.api.saas_chatbot_models import (
    ChatbotActor,
    ChatbotCreation,
    ChatbotDefinition,
    ChatbotRecord,
    ChatbotStatus,
    ChatbotUpdate,
    ChatbotVersionMutation,
)
from src.api.saas_identity import JwtClaims
from src.api.saas_security import BffSessionHandle
from src.api.saas_sessions import BffSession, Membership, WorkspaceRole


@dataclass(frozen=True, slots=True)
class _FakeAuthResolver:
    context: AuthContext

    async def resolve(
        self, request: Request, *, require_workspace: bool
    ) -> AuthContext:
        del request, require_workspace
        return self.context


class _RecordingChatbots:
    def __init__(self, record: ChatbotRecord) -> None:
        self.record = record
        self.available = True
        self.calls: list[str] = []
        self.channels: list[ExecutionChannel] = []

    async def list_chatbots(self, actor: ChatbotActor) -> tuple[ChatbotRecord, ...]:
        del actor
        self.calls.append("list")
        return (self.record,)

    async def get_chatbot(self, actor: ChatbotActor, chatbot_id: UUID) -> ChatbotRecord:
        del actor, chatbot_id
        self.calls.append("get")
        return self.record

    async def create_chatbot(self, command: ChatbotCreation) -> ChatbotRecord:
        del command
        self.calls.append("create")
        return self.record

    async def update_chatbot(self, command: ChatbotUpdate) -> ChatbotRecord:
        del command
        self.calls.append("update")
        return self.record

    async def disable_chatbot(self, command: ChatbotVersionMutation) -> ChatbotRecord:
        del command
        self.calls.append("disable")
        return self.record

    async def archive_chatbot(self, command: ChatbotVersionMutation) -> None:
        del command
        self.calls.append("archive")

    async def resolve_execution(
        self,
        workspace_id: UUID,
        chatbot_id: UUID,
        channel: ExecutionChannel,
        locale: SupportedLocale,
    ) -> ChatbotExecutionConfiguration:
        del workspace_id, chatbot_id, locale
        self.channels.append(channel)
        if not self.available:
            raise ChatbotUnavailableError
        return ChatbotExecutionConfiguration(
            configuration=ChatbotConfiguration(
                provider="ollama",
                model_name="local-model",
                instructions="Use workspace knowledge.",
                workspace_all=True,
            ),
            channel=channel,
        )


def _auth_context(
    workspace_id: UUID, user_id: UUID, role: WorkspaceRole
) -> AuthContext:
    session = BffSession(
        handle=BffSessionHandle("opaque-chatbot-test-handle"),
        user_id=user_id,
        email="actor@example.test",
        access_token="server-only-access",
        refresh_token="server-only-refresh",
        expires_at=99_999_999_999.0,
        active_workspace_id=workspace_id,
    )
    return AuthContext(
        session=session,
        claims=JwtClaims(user_id=user_id, email=session.email),
        membership=Membership(workspace_id, role),
    )


def _definition() -> ChatbotDefinition:
    return ChatbotDefinition(
        name_en="Support",
        name_ru="Поддержка",
        instructions_en="Use approved sources.",
        instructions_ru="Используй разрешённые источники.",
        provider="ollama",
        model_name="local-model",
    )


def _record(workspace_id: UUID) -> ChatbotRecord:
    return ChatbotRecord(
        id=uuid4(),
        workspace_id=workspace_id,
        definition=_definition(),
        status=ChatbotStatus.ENABLED,
        version=1,
    )


def test_chatbot_lifecycle_contract_is_available_to_tenant_chat() -> None:
    # Given: Task 8 exposes only session-scoped chat primitives.
    # When: Task 9 asks for an authoritative lifecycle execution channel.
    # Then: the typed lifecycle contract must exist at the chat boundary.
    assert hasattr(saas_chat_models, "ExecutionChannel")
    assert tuple(ExecutionChannel) == (
        ExecutionChannel.TEST,
        ExecutionChannel.PUBLIC_WIDGET,
    )


@pytest.mark.anyio
async def test_manager_routes_validate_localized_fields_and_member_is_read_only() -> (
    None
):
    # Given: one selected workspace and a workspace-owned chatbot service.
    workspace_id, user_id = uuid4(), uuid4()
    service = _RecordingChatbots(_record(workspace_id))
    manager_app = FastAPI()
    manager_app.include_router(
        create_saas_chatbots_router(
            _FakeAuthResolver(
                _auth_context(workspace_id, user_id, WorkspaceRole.ADMIN)
            ),
            service,
        )
    )
    prefix = f"/api/saas/workspaces/{workspace_id}/chatbots"
    valid = {
        "name": {"en": "Support", "ru": "Поддержка"},
        "instructions": {
            "en": "Use approved sources.",
            "ru": "Используй разрешённые источники.",
        },
        "provider": "ollama",
        "model_name": "local-model",
        "source_scope": "workspace_all",
    }

    # When: the admin creates and lists, while an invalid localized update arrives.
    async with AsyncClient(
        transport=ASGITransport(app=manager_app), base_url="http://test"
    ) as client:
        created = await client.post(
            prefix, headers={"Idempotency-Key": "chatbot-create-1"}, json=valid
        )
        listed = await client.get(prefix)
        updated = await client.patch(
            f"{prefix}/{service.record.id}", json={**valid, "version": 1}
        )
        disabled = await client.post(
            f"{prefix}/{service.record.id}/disable", json={"version": 1}
        )
        archived = await client.request(
            "DELETE",
            f"{prefix}/{service.record.id}",
            json={"version": 1},
        )
        invalid = await client.patch(
            f"{prefix}/{service.record.id}",
            json={**valid, "name": {"en": "Support", "ru": ""}, "version": 1},
        )

    # Then: valid manager operations reach the service and invalid fields do not.
    assert created.status_code == 201
    assert created.json()["source_scope"] == "workspace_all"
    assert listed.json()[0]["name"]["ru"] == "Поддержка"
    assert updated.status_code == 200
    assert disabled.status_code == 200
    assert archived.status_code == 204
    assert invalid.status_code == 422
    assert service.calls == ["create", "list", "update", "disable", "archive"]

    member_app = FastAPI()
    member_app.include_router(
        create_saas_chatbots_router(
            _FakeAuthResolver(
                _auth_context(workspace_id, user_id, WorkspaceRole.MEMBER)
            ),
            service,
        )
    )
    async with AsyncClient(
        transport=ASGITransport(app=member_app), base_url="http://test"
    ) as client:
        denied = await client.post(
            prefix, headers={"Idempotency-Key": "chatbot-create-2"}, json=valid
        )
        visible = await client.get(prefix)
    assert denied.status_code == 403
    assert visible.status_code == 200


@pytest.mark.anyio
async def test_member_session_creation_uses_test_guard_and_disabled_state_blocks(
    tmp_path: Path,
) -> None:
    # Given: an authenticated member, tenant runtime, and authoritative catalog.
    workspace_id, user_id = uuid4(), uuid4()
    service = _RecordingChatbots(_record(workspace_id))
    runtime = TenantChatRuntime(
        TenantChatStore(tmp_path / "tenant-chat.sqlite3"), b"task9-server-key", 2
    )
    await runtime.initialize()
    app = FastAPI()
    app.include_router(
        create_saas_chat_router(
            _FakeAuthResolver(
                _auth_context(workspace_id, user_id, WorkspaceRole.MEMBER)
            ),
            runtime,
            service,
        )
    )
    prefix = (
        f"/api/saas/workspaces/{workspace_id}/chatbots/{service.record.id}/sessions"
    )

    # When: the member opens one enabled test session, then the chatbot is disabled.
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        enabled = await client.post(prefix, json={"title": "Test"})
        service.available = False
        blocked = await client.post(prefix, json={"title": "Blocked"})

    # Then: test traffic is explicit and disabled new conversations fail closed.
    assert enabled.status_code == 201
    assert blocked.status_code == 409
    assert service.channels == [ExecutionChannel.TEST, ExecutionChannel.TEST]

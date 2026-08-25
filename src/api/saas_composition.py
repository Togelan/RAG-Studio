"""Composition root for authenticated SaaS routes and server authorities."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Never, assert_never

from fastapi import FastAPI
from pydantic import SecretStr

from src.api.chat_stream import MAX_CONCURRENT_STREAMS
from src.api.personal_lab_registry import (
    PersonalLabRouteDependencies,
    PersonalLabRouterRegistry,
)
from src.api.personal_lab_scope import (
    PersonalLabScopeResolver,
    PostgresPersonalLabScopeRegistry,
)
from src.api.react_ui import (
    UiMode,
    UiServingConfiguration,
    load_ui_serving_configuration,
)
from src.api.routes.personal_chat import create_personal_chat_router
from src.api.routes.personal_lab import create_personal_lab_router
from src.api.routes.personal_settings import create_personal_settings_router
from src.api.routes.saas_auth import create_saas_auth_router
from src.api.routes.saas_auth_confirmation import (
    SupabaseConfirmationVerifier,
    create_saas_auth_confirmation_router,
)
from src.api.routes.saas_chat import create_saas_chat_router
from src.api.routes.saas_chatbots import create_saas_chatbots_router
from src.api.routes.saas_rag import create_saas_rag_router
from src.api.routes.saas_tenant_health import create_saas_tenant_health_router
from src.api.routes.saas_workspaces import create_saas_workspaces_router
from src.api.saas_account_context import PostgresAccountContextResolver
from src.api.saas_account_store import PostgresAccountStore
from src.api.saas_auth_context import BffAuthContextResolver
from src.api.saas_chat_persistence import TenantChatStore
from src.api.saas_chat_runtime import TenantChatRuntime
from src.api.saas_chatbot_store import PostgresChatbotService
from src.api.saas_collection_registry import PostgresWorkspaceCollectionRegistry
from src.api.saas_identity import SupabaseAccessTokenVerifier, SupabaseIdentityProvider
from src.api.saas_runtime import (
    RuntimeConfiguration,
    RuntimeMode,
    SaasConfigurationError,
)
from src.api.saas_session_crypto import SessionKeyRing
from src.api.saas_session_store import PostgresBffSessionStore
from src.api.saas_tenant_graph import PersistentTenantGraphRunner
from src.api.saas_workspace_context import PostgresMembershipResolver
from src.api.saas_workspaces import create_postgres_workspace_service
from src.graph.llm_provider import OpenAIProviderFactory
from src.ingestion.embedder import get_embedder
from src.ingestion.personal_router import create_personal_knowledge_router
from src.paths import data_path
from src.vector_store.client import get_qdrant_client
from src.vector_store.tenant_resolver import TrustedTenantRagResolver


@dataclass(frozen=True, slots=True)
class _SaasAuthorities:
    identity: SupabaseIdentityProvider
    identity_base_url: str
    token_verifier: SupabaseAccessTokenVerifier
    account_store: PostgresAccountStore
    account_context: PostgresAccountContextResolver
    sessions: PostgresBffSessionStore
    memberships: PostgresMembershipResolver
    auth_context: BffAuthContextResolver
    collections: PostgresWorkspaceCollectionRegistry
    chat_runtime: TenantChatRuntime
    chatbots: PostgresChatbotService
    graph_runner: PersistentTenantGraphRunner
    database_url: str
    session_signing_key: SecretStr


class InvalidApplicationModeError(ValueError):
    """Raised when runtime and UI modes do not form an approved composition."""


def load_application_ui_configuration(
    runtime_mode: RuntimeMode,
) -> UiServingConfiguration:
    """Load UI configuration and enforce the closed runtime/UI mode matrix."""
    if "RAG_STUDIO_UI_MODE" not in os.environ and runtime_mode is RuntimeMode.LOCAL:
        configuration = UiServingConfiguration(mode=UiMode.LEGACY, react_build=None)
    else:
        configuration = load_ui_serving_configuration()
    _validate_application_mode(runtime_mode, configuration.mode)
    return configuration


def _validate_application_mode(runtime_mode: RuntimeMode, ui_mode: UiMode) -> None:
    match runtime_mode:
        case RuntimeMode.SAAS:
            match ui_mode:
                case UiMode.REACT:
                    return
                case UiMode.LEGACY:
                    _raise_invalid_application_mode()
                case unreachable:
                    assert_never(unreachable)
        case RuntimeMode.LOCAL:
            match ui_mode:
                case UiMode.LEGACY:
                    return
                case UiMode.REACT:
                    _raise_invalid_application_mode()
                case unreachable:
                    assert_never(unreachable)
        case unreachable:
            assert_never(unreachable)


def _raise_invalid_application_mode() -> Never:
    raise InvalidApplicationModeError(
        "RAG-Studio requires either SaaS with React or local with Legacy UI."
    )


def mount_saas_routes(
    app: FastAPI, runtime: RuntimeConfiguration
) -> BffAuthContextResolver:
    """Mount authenticated routes and return their shared request authority."""
    authorities = _build_authorities(runtime)
    app.state.saas_session_store = authorities.sessions
    app.state.saas_collection_registry = authorities.collections
    app.state.saas_chat_runtime = authorities.chat_runtime
    app.state.saas_chatbot_service = authorities.chatbots
    _mount_identity_routes(app, authorities)
    _mount_tenant_routes(app, authorities)
    _mount_personal_lab_routes(app, authorities)
    return authorities.auth_context


def _mount_personal_lab_routes(app: FastAPI, authority: _SaasAuthorities) -> None:
    registry = PersonalLabRouterRegistry()
    registry.register("context", create_personal_lab_router)
    registry.register("chat", create_personal_chat_router)
    registry.register("settings", create_personal_settings_router)
    registry.register("knowledge", create_personal_knowledge_router)
    dependencies = PersonalLabRouteDependencies(
        auth_context=authority.auth_context,
        scopes=PersonalLabScopeResolver(
            PostgresPersonalLabScopeRegistry(authority.database_url),
            data_path("personal-labs"),
        ),
    )
    for router in registry.build(dependencies):
        app.include_router(router)
    app.state.personal_lab_router_registry = registry
    app.state.personal_lab_scope_resolver = dependencies.scopes


def _build_authorities(runtime: RuntimeConfiguration) -> _SaasAuthorities:
    supabase_url = runtime.supabase_url
    jwt_issuer = runtime.jwt_issuer
    jwt_audience = runtime.jwt_audience
    database = runtime.database_url
    signing_key = runtime.session_signing_key
    if (
        supabase_url is None
        or jwt_issuer is None
        or jwt_audience is None
        or database is None
        or signing_key is None
    ):
        raise SaasConfigurationError(
            "Validated SaaS identity configuration is unavailable."
        )
    database_url = database.get_secret_value()
    identity = SupabaseIdentityProvider(str(supabase_url))
    account_store = PostgresAccountStore(database_url)
    account_context = PostgresAccountContextResolver(account_store)
    sessions = PostgresBffSessionStore(database_url, SessionKeyRing.from_environment())
    token_verifier = SupabaseAccessTokenVerifier(
        provider=identity, issuer=str(jwt_issuer), audience=jwt_audience
    )
    memberships = PostgresMembershipResolver(database_url)
    auth_context = BffAuthContextResolver(
        token_verifier, sessions, memberships, account_context
    )
    collections = PostgresWorkspaceCollectionRegistry(database_url)
    chat_runtime = TenantChatRuntime(
        store=TenantChatStore(data_path("tenant-chat", "chat.sqlite3")),
        execution_signing_key=signing_key.get_secret_value().encode(),
        capacity=MAX_CONCURRENT_STREAMS,
    )
    return _SaasAuthorities(
        identity=identity,
        identity_base_url=str(supabase_url),
        token_verifier=token_verifier,
        account_store=account_store,
        account_context=account_context,
        sessions=sessions,
        memberships=memberships,
        auth_context=auth_context,
        collections=collections,
        chat_runtime=chat_runtime,
        chatbots=PostgresChatbotService(database_url),
        graph_runner=PersistentTenantGraphRunner(
            checkpoint_path=str(data_path("checkpoints", "checkpoints.db")),
            provider_factory=OpenAIProviderFactory(),
            embedder=get_embedder(),
        ),
        database_url=database_url,
        session_signing_key=signing_key,
    )


def _mount_identity_routes(app: FastAPI, authority: _SaasAuthorities) -> None:
    app.include_router(
        create_saas_auth_router(
            identity_provider=authority.identity,
            token_verifier=authority.token_verifier,
            session_store=authority.sessions,
            membership_resolver=authority.memberships,
            account_context_resolver=authority.account_context,
            account_bootstrapper=authority.account_store,
        )
    )
    app.include_router(
        create_saas_auth_confirmation_router(
            completion_url="/app",
            verifier=SupabaseConfirmationVerifier(authority.identity_base_url),
        )
    )
    app.include_router(
        create_saas_workspaces_router(
            authority.auth_context,
            create_postgres_workspace_service(
                authority.database_url, authority.session_signing_key
            ),
        )
    )


def _mount_tenant_routes(app: FastAPI, authority: _SaasAuthorities) -> None:
    app.include_router(
        create_saas_tenant_health_router(
            auth_context_resolver=authority.auth_context,
            registry=authority.collections,
        )
    )
    app.include_router(
        create_saas_chatbots_router(authority.auth_context, authority.chatbots)
    )
    resolver = TrustedTenantRagResolver(authority.collections, get_qdrant_client)
    app.include_router(
        create_saas_chat_router(
            authority.auth_context,
            authority.chat_runtime,
            authority.chatbots,
            store_resolver=resolver,
            graph_runner=authority.graph_runner,
        )
    )
    app.include_router(
        create_saas_rag_router(
            authority.auth_context,
            resolver,
            get_embedder(),
            authority.chatbots,
        )
    )

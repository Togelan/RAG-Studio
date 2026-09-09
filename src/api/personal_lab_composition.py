"""Composition boundary for explicitly registered Personal Lab routes."""

from __future__ import annotations

from functools import partial

from fastapi import FastAPI

from src.api.billing_runtime import create_stripe_client
from src.api.mvp_billing_store import PostgresMvpBillingStore
from src.api.mvp_local_demo import create_mvp_local_demo_router
from src.api.mvp_publication_store import PostgresMvpPublicationStore
from src.api.mvp_stripe_gateway import (
    StripeBillingGateway,
    StripeWebhookSignatureVerifier,
)
from src.api.personal_lab_registry import (
    PersonalLabRouteDependencies,
    PersonalLabRouterRegistry,
)
from src.api.personal_lab_scope import (
    PersonalLabScopeResolver,
    PostgresPersonalLabScopeRegistry,
)
from src.api.routes.mvp_billing import create_mvp_billing_router
from src.api.routes.mvp_billing_projection import create_mvp_billing_projection_router
from src.api.routes.mvp_publication import create_mvp_publication_router
from src.api.routes.personal_chat import create_personal_chat_router
from src.api.routes.personal_lab import create_personal_lab_router
from src.api.routes.personal_settings import create_personal_settings_router
from src.api.saas_auth_context import BffAuthContextResolver
from src.ingestion.personal_router import create_personal_knowledge_router
from src.paths import data_path


def mount_personal_lab_routes(
    app: FastAPI, auth_context: BffAuthContextResolver, database_url: str
) -> None:
    """Mount Personal Lab leaves from shared identity and scope authorities."""
    registry = PersonalLabRouterRegistry()
    registry.register("context", create_personal_lab_router)
    registry.register("chat", create_personal_chat_router)
    registry.register("settings", create_personal_settings_router)
    registry.register("knowledge", create_personal_knowledge_router)
    runtime = app.state.runtime_configuration
    if runtime.local_demo_mode:
        registry.register("local-demo", create_mvp_local_demo_router)
    if runtime.publication_enabled:
        registry.register(
            "publication",
            partial(
                create_mvp_publication_router,
                store=PostgresMvpPublicationStore(database_url),
            ),
        )
    billing = runtime.billing
    if billing is not None:
        registry.register(
            "billing-projection",
            partial(
                create_mvp_billing_projection_router,
                configuration=billing,
                store=PostgresMvpBillingStore(database_url),
            ),
        )
        registry.register(
            "billing",
            partial(
                create_mvp_billing_router,
                configuration=billing,
                gateway=StripeBillingGateway(create_stripe_client(billing)),
                verifier=StripeWebhookSignatureVerifier(
                    billing.webhook_secret.get_secret_value()
                ),
                store=PostgresMvpBillingStore(database_url),
            ),
        )
    dependencies = PersonalLabRouteDependencies(
        auth_context=auth_context,
        scopes=PersonalLabScopeResolver(
            PostgresPersonalLabScopeRegistry(database_url),
            data_path("personal-labs"),
        ),
    )
    for router in registry.build(dependencies):
        app.include_router(router)
    app.state.personal_lab_router_registry = registry
    app.state.personal_lab_scope_resolver = dependencies.scopes

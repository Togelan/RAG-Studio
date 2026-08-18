"""Tenant-bound LangGraph execution for authenticated SaaS chat."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Protocol

from src.api.saas_chat_models import ChatbotConfiguration
from src.api.saas_chat_scope import ExecutionKey
from src.graph import create_graph, stream_rag_graph
from src.graph.llm_provider import LLMProviderFactory
from src.ingestion.embedding import Embedder
from src.vector_store.tenant_store import TenantCacheScope, TenantRagStore


class TenantGraphRunner(Protocol):
    """Execute one graph turn through an already authorized tenant store."""

    def stream(
        self,
        *,
        query: str,
        thread_id: ExecutionKey,
        configuration: ChatbotConfiguration,
        api_key: str | None,
        tenant_store: TenantRagStore,
    ) -> AsyncIterator[Mapping[str, object]]: ...


@dataclass(frozen=True, slots=True)
class PersistentTenantGraphRunner:
    """Compile each SaaS turn with its exact tenant store and shared checkpoint file."""

    checkpoint_path: str
    provider_factory: LLMProviderFactory
    embedder: Embedder

    async def stream(
        self,
        *,
        query: str,
        thread_id: ExecutionKey,
        configuration: ChatbotConfiguration,
        api_key: str | None,
        tenant_store: TenantRagStore,
    ) -> AsyncIterator[Mapping[str, object]]:
        """Yield one tenant-bound graph stream without a global vector-store fallback."""
        cache_scope = TenantCacheScope(str(configuration.fingerprint))
        async with create_graph(
            db_path=self.checkpoint_path,
            provider_factory=self.provider_factory,
            embedder=self.embedder,
            tenant_store=tenant_store,
            cache_scope=cache_scope,
            provider_api_key=api_key,
        ) as compiled_graph:
            async for event in stream_rag_graph(
                query=query,
                session_id=str(thread_id),
                persist_user_api_key=False,
                compiled_graph=compiled_graph,
                provider=configuration.provider,
                model=configuration.model_name,
                system_prompt=configuration.instructions,
            ):
                yield event

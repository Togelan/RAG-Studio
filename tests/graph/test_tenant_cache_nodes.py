from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage

from src.graph.nodes import cache_check_node, save_to_cache_node
from src.graph.state import RAGState
from src.vector_store.models import DenseVector, SparseVector
from src.vector_store.tenant_store import SemanticCacheHit, TenantCacheScope


class FakeEmbedder:
    def embed_dense(self, texts: tuple[str, ...]) -> tuple[DenseVector, ...]:
        return tuple(DenseVector((1.0,) * 384) for _ in texts)

    def embed_sparse(self, texts: tuple[str, ...]) -> tuple[SparseVector, ...]:
        return tuple(SparseVector((1,), (1.0,)) for _ in texts)


class PoisonLegacyStore:
    async def ensure_collection(self, collection: object) -> None:
        del collection
        raise AssertionError("legacy cache reached")


class RecordingTenantCache:
    def __init__(self, hit: SemanticCacheHit | None = None) -> None:
        self.hit = hit
        self.lookups: list[TenantCacheScope] = []
        self.saves: list[tuple[TenantCacheScope, str, str]] = []

    async def lookup_cache(
        self, scope: TenantCacheScope, dense: DenseVector
    ) -> SemanticCacheHit | None:
        del dense
        self.lookups.append(scope)
        return self.hit

    async def save_cache(
        self,
        scope: TenantCacheScope,
        query: str,
        answer: str,
        dense: DenseVector,
    ) -> None:
        del dense
        self.saves.append((scope, query, answer))


def _state() -> RAGState:
    return {
        "messages": [HumanMessage(content="question")],
        "query": "question",
        "intent": "standalone_question",
        "cache_hit": False,
        "cached_answer": None,
        "retrieved_docs": [],
        "reranked_docs": [],
        "generated_from": "retrieval",
        "final_answer": "answer",
        "faithfulness_score": 1.0,
        "validation_passed": True,
        "session_id": "session",
        "user_api_key": None,
        "provider": "deepseek",
        "model_name": "deepseek-chat",
        "temperature": 0.3,
        "max_tokens": 1024,
        "system_prompt": "",
        "top_k": 5,
    }


@pytest.mark.anyio
async def test_cache_check_uses_only_bound_tenant_and_config_scope() -> None:
    # Given: a bound cache hit and a legacy store that must never be reached.
    scope = TenantCacheScope(f"cfg_{'a' * 64}")
    tenant_cache = RecordingTenantCache(SemanticCacheHit("tenant answer", 0.99))

    # When: the graph cache node receives the complete tenant binding.
    result = await cache_check_node(
        _state(),
        vector_store=PoisonLegacyStore(),
        embedder=FakeEmbedder(),
        tenant_store=tenant_cache,
        cache_scope=scope,
    )

    # Then: only the bound cache is read and its answer is returned.
    assert result == {"cache_hit": True, "cached_answer": "tenant answer"}
    assert tenant_cache.lookups == [scope]


@pytest.mark.anyio
async def test_partial_tenant_cache_binding_fails_closed_without_global_fallback() -> None:
    # Given: a tenant store without its chatbot configuration fingerprint.
    tenant_cache = RecordingTenantCache(SemanticCacheHit("poison", 1.0))

    # When: cache lookup lacks the complete tenant binding.
    result = await cache_check_node(
        _state(),
        vector_store=PoisonLegacyStore(),
        embedder=FakeEmbedder(),
        tenant_store=tenant_cache,
        cache_scope=None,
    )

    # Then: the node returns a miss and touches neither tenant nor global cache.
    assert result == {"cache_hit": False, "cached_answer": None}
    assert tenant_cache.lookups == []


@pytest.mark.anyio
async def test_cache_save_uses_only_bound_tenant_and_config_scope() -> None:
    # Given: a validated answer and a complete tenant cache binding.
    scope = TenantCacheScope(f"cfg_{'b' * 64}")
    tenant_cache = RecordingTenantCache()

    # When: the graph persists the semantic-cache answer.
    result = await save_to_cache_node(
        _state(),
        vector_store=PoisonLegacyStore(),
        embedder=FakeEmbedder(),
        tenant_store=tenant_cache,
        cache_scope=scope,
    )

    # Then: only the bound cache receives the scoped query and answer.
    assert result == {}
    assert tenant_cache.saves == [(scope, "question", "answer")]

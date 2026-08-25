from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import anyio
import pytest
from pydantic import SecretStr

from src.api.personal_lab_scope import PersonalLabScope
from src.api.personal_lab_settings import PersonalSettings, PersonalSettingsRecord
from src.graph import personal_lab_execution
from src.graph.llm_provider import LLMProviderConfig
from src.graph.personal_lab_execution import run_personal_lab_graph


class _ImmediateSettingsStore:
    def load(self, scope: PersonalLabScope) -> PersonalSettingsRecord:
        del scope
        return PersonalSettingsRecord(PersonalSettings(), {})


class _ImmediateVectorStore:
    pass


class _ImmediateEmbedder:
    pass


class _MutableSettingsStore:
    def __init__(self, record: PersonalSettingsRecord) -> None:
        self.record = record

    def load(self, scope: PersonalLabScope) -> PersonalSettingsRecord:
        del scope
        return self.record


class _CapturingProviderFactory:
    def __init__(self) -> None:
        self.configs: list[LLMProviderConfig] = []

    def __call__(self, config: LLMProviderConfig) -> object:
        self.configs.append(config)
        return object()


def _scope(root: Path) -> PersonalLabScope:
    scope_id = uuid4()
    namespace = f"pl_{scope_id.hex}"
    return PersonalLabScope(scope_id, namespace, root / namespace, namespace)


def _ok_result() -> dict[str, object]:
    return {
        "final_answer": "ok",
        "generated_from": "cache",
        "faithfulness_score": 1.0,
        "retrieved_docs": [],
    }


type _Capabilities = tuple[
    _CapturingProviderFactory, _ImmediateEmbedder, _ImmediateVectorStore
]


async def _overlap_lifecycle_count(
    monkeypatch: pytest.MonkeyPatch,
    calls: tuple[tuple[PersonalLabScope, _Capabilities], ...],
) -> tuple[int, float]:
    all_started = anyio.Event()
    lifecycle_entries = 0
    started_turns = 0

    @asynccontextmanager
    async def immediate_graph(*_: object, **__: object):
        nonlocal lifecycle_entries
        lifecycle_entries += 1
        await anyio.sleep(0.025)
        yield object()

    async def immediate_run(*_: object, **__: object) -> dict[str, object]:
        nonlocal started_turns
        started_turns += 1
        if started_turns == len(calls):
            all_started.set()
        await all_started.wait()
        return _ok_result()

    monkeypatch.setattr(personal_lab_execution, "create_graph", immediate_graph)
    monkeypatch.setattr(personal_lab_execution, "run_rag_graph", immediate_run)

    async def execute(scope: PersonalLabScope, capabilities: _Capabilities) -> None:
        provider, embedder, vector_store = capabilities
        await run_personal_lab_graph(
            scope,
            query="synthetic",
            session_id=f"session-{uuid4().hex}",
            settings_store=_ImmediateSettingsStore(),
            provider_factory=provider,  # type: ignore[arg-type]
            embedder=embedder,  # type: ignore[arg-type]
            vector_store=vector_store,  # type: ignore[arg-type]
        )

    started = perf_counter()
    async with anyio.create_task_group() as tasks:
        for scope, capabilities in calls:
            tasks.start_soon(execute, scope, capabilities)
    return lifecycle_entries, perf_counter() - started


@pytest.mark.asyncio
async def test_concurrent_personal_turns_share_one_graph_lifecycle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scope = _scope(tmp_path)
    capabilities = (
        _CapturingProviderFactory(),
        _ImmediateEmbedder(),
        _ImmediateVectorStore(),
    )
    calls = tuple((scope, capabilities) for _ in range(10))
    lifecycle_entries, elapsed = await _overlap_lifecycle_count(monkeypatch, calls)
    assert lifecycle_entries == 1, "each turn opened its own graph/checkpointer"
    assert elapsed < 0.15, "graph lifecycle setup serialized the ten-turn burst"


@pytest.mark.asyncio
async def test_overlapping_personal_scopes_use_independent_graph_lifecycles(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    capabilities = (
        _CapturingProviderFactory(),
        _ImmediateEmbedder(),
        _ImmediateVectorStore(),
    )
    calls = tuple((_scope(tmp_path), capabilities) for _ in range(2))
    assert (await _overlap_lifecycle_count(monkeypatch, calls))[0] == 2


@pytest.mark.parametrize("distinct_capability", range(3))
@pytest.mark.asyncio
async def test_distinct_injected_capabilities_do_not_share_graph_lifecycle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, distinct_capability: int
) -> None:
    scope = _scope(tmp_path)
    first: _Capabilities = (
        _CapturingProviderFactory(),
        _ImmediateEmbedder(),
        _ImmediateVectorStore(),
    )
    second = list(first)
    second[distinct_capability] = (
        _CapturingProviderFactory(),
        _ImmediateEmbedder(),
        _ImmediateVectorStore(),
    )[distinct_capability]
    calls = ((scope, first), (scope, tuple(second)))  # type: ignore[arg-type]
    assert (await _overlap_lifecycle_count(monkeypatch, calls))[0] == 2


@pytest.mark.asyncio
async def test_idle_graph_rebuilds_after_settings_secret_changes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scope = _scope(tmp_path)
    settings_store = _MutableSettingsStore(
        PersonalSettingsRecord(
            PersonalSettings(provider="openai", model="model-a"),
            {"openai": "secret-a"},
        )
    )
    provider_factory = _CapturingProviderFactory()
    lifecycle_entries = 0

    @asynccontextmanager
    async def immediate_graph(*_: object, **kwargs: object):
        nonlocal lifecycle_entries
        lifecycle_entries += 1
        yield kwargs["provider_factory"]

    async def immediate_run(*_: object, **kwargs: object) -> dict[str, object]:
        selected_factory = kwargs["compiled_graph"]
        selected_factory(
            LLMProviderConfig(
                provider=str(kwargs["provider"]),
                base_url=None,
                model=str(kwargs["model"]),
                api_key=None,
                temperature=0.0,
                max_tokens=1,
                deadline=1.0,
            )
        )
        return _ok_result()

    monkeypatch.setattr(personal_lab_execution, "create_graph", immediate_graph)
    monkeypatch.setattr(personal_lab_execution, "run_rag_graph", immediate_run)
    vector_store = _ImmediateVectorStore()

    await run_personal_lab_graph(
        scope,
        query="first",
        session_id="session-first",
        settings_store=settings_store,
        provider_factory=provider_factory,  # type: ignore[arg-type]
        vector_store=vector_store,  # type: ignore[arg-type]
    )
    settings_store.record = PersonalSettingsRecord(
        PersonalSettings(provider="openai", model="model-b"),
        {"openai": "secret-b"},
    )
    await run_personal_lab_graph(
        scope,
        query="second",
        session_id="session-second",
        settings_store=settings_store,
        provider_factory=provider_factory,  # type: ignore[arg-type]
        vector_store=vector_store,  # type: ignore[arg-type]
    )

    assert lifecycle_entries == 2
    assert [config.model for config in provider_factory.configs] == [
        "model-a",
        "model-b",
    ]
    assert [
        config.api_key.get_secret_value()
        if isinstance(config.api_key, SecretStr)
        else None
        for config in provider_factory.configs
    ] == ["secret-a", "secret-b"]


@pytest.mark.asyncio
async def test_cancelled_personal_turn_releases_graph_lease(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scope = _scope(tmp_path)
    first_started = anyio.Event()
    block = True
    lifecycle_entries = 0
    lifecycle_exits = 0

    @asynccontextmanager
    async def immediate_graph(*_: object, **__: object):
        nonlocal lifecycle_entries, lifecycle_exits
        lifecycle_entries += 1
        try:
            yield object()
        finally:
            lifecycle_exits += 1

    async def controlled_run(*_: object, **__: object) -> dict[str, object]:
        if block:
            first_started.set()
            await anyio.sleep_forever()
        return _ok_result()

    monkeypatch.setattr(personal_lab_execution, "create_graph", immediate_graph)
    monkeypatch.setattr(personal_lab_execution, "run_rag_graph", controlled_run)
    vector_store = _ImmediateVectorStore()

    async def execute() -> None:
        await run_personal_lab_graph(
            scope,
            query="cancel",
            session_id="session-cancelled",
            settings_store=_ImmediateSettingsStore(),
            vector_store=vector_store,  # type: ignore[arg-type]
        )

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(execute)
        await first_started.wait()
        tasks.cancel_scope.cancel()

    block = False
    result = await run_personal_lab_graph(
        scope,
        query="retry",
        session_id="session-retry",
        settings_store=_ImmediateSettingsStore(),
        vector_store=vector_store,  # type: ignore[arg-type]
    )

    assert result["final_answer"] == "ok"
    assert lifecycle_entries == 2
    assert lifecycle_exits == 2

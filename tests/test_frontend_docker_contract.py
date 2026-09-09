from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pytest

from src.api.react_ui import UiMode
from src.api.saas_composition import load_application_ui_configuration
from src.api.saas_runtime import RuntimeMode

PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
DOCKERFILE_PATH: Final = PROJECT_ROOT / "Dockerfile"
COMPOSE_PATH: Final = PROJECT_ROOT / "docker-compose.yml"
RUNTIME_REQUIREMENTS_PATH: Final = PROJECT_ROOT / "requirements-runtime.txt"
ENV_EXAMPLE_PATH: Final = PROJECT_ROOT / ".env.example"


@dataclass(frozen=True, slots=True)
class DockerStage:
    base: str
    name: str | None
    instructions: tuple[str, ...]


def _docker_stages() -> tuple[DockerStage, ...]:
    stages: list[DockerStage] = []
    base = ""
    name: str | None = None
    instructions: list[str] = []

    for raw_line in DOCKERFILE_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("FROM "):
            if base:
                stages.append(DockerStage(base, name, tuple(instructions)))
            image, separator, stage_name = line.removeprefix("FROM ").partition(" AS ")
            base = image
            name = stage_name if separator else None
            instructions = []
            continue
        instructions.append(line)

    assert base
    stages.append(DockerStage(base, name, tuple(instructions)))
    return tuple(stages)


def _stage_named(name: str) -> DockerStage:
    matches = [stage for stage in _docker_stages() if stage.name == name]
    assert len(matches) == 1
    return matches[0]


def _compose_service_names() -> tuple[str, ...]:
    names: list[str] = []
    in_services = False
    for raw_line in COMPOSE_PATH.read_text(encoding="utf-8").splitlines():
        if raw_line == "services:":
            in_services = True
            continue
        if in_services and raw_line and not raw_line.startswith(" "):
            break
        if (
            in_services
            and raw_line.startswith("  ")
            and not raw_line.startswith("    ")
        ):
            name, separator, _ = raw_line.strip().partition(":")
            if separator:
                names.append(name)
    return tuple(names)


def _compose_environment() -> tuple[str, ...]:
    values: list[str] = []
    in_environment = False
    for raw_line in COMPOSE_PATH.read_text(encoding="utf-8").splitlines():
        if raw_line == "    environment:":
            in_environment = True
            continue
        if in_environment and raw_line.startswith("      - "):
            values.append(raw_line.removeprefix("      - "))
            continue
        if in_environment and raw_line.startswith("    ") and raw_line.strip():
            break
    return tuple(values)


def _environment_template_value(name: str) -> str:
    prefix = f"{name}="
    values = [
        line.removeprefix(prefix)
        for line in ENV_EXAMPLE_PATH.read_text(encoding="utf-8").splitlines()
        if line.startswith(prefix)
    ]
    assert len(values) == 1
    return values[0]


def test_node_builder_installs_lockfile_before_building_assets() -> None:
    builder = _stage_named("frontend-builder")
    assert builder.base.startswith("node:24.19.0")

    instructions = list(builder.instructions)
    lockfile_copy = "COPY frontend/package.json frontend/package-lock.json ./"
    source_copy = "COPY frontend/ ./"
    locale_copy = "COPY src/api/locales/ /src/api/locales/"
    assert lockfile_copy in instructions
    assert "RUN npm ci" in instructions
    assert source_copy in instructions
    assert locale_copy in instructions
    assert "RUN npm run build" in instructions
    assert instructions.index(lockfile_copy) < instructions.index("RUN npm ci")
    assert instructions.index(source_copy) < instructions.index("RUN npm run build")
    assert instructions.index(locale_copy) < instructions.index("RUN npm run build")


def test_widget_builder_installs_lockfile_before_building_assets() -> None:
    builder = _stage_named("widget-builder")
    assert builder.base == "node:24.19.0-bookworm-slim"

    instructions = list(builder.instructions)
    lockfile_copy = "COPY widget/package.json widget/package-lock.json ./"
    source_copy = "COPY widget/ ./"
    assert lockfile_copy in instructions
    assert "RUN npm ci" in instructions
    assert source_copy in instructions
    assert "RUN npm run build" in instructions
    assert instructions.index(lockfile_copy) < instructions.index("RUN npm ci")
    assert instructions.index(source_copy) < instructions.index("RUN npm run build")


def test_python_runtime_copies_only_built_asset_artifacts_from_builders() -> None:
    runtime = _docker_stages()[-1]
    assert runtime.base == "python:3.14-slim"

    builder_copies = [
        instruction
        for instruction in runtime.instructions
        if instruction.startswith("COPY --from=")
    ]
    assert builder_copies == [
        "COPY --from=frontend-builder /frontend/dist ./frontend/dist",
        "COPY --from=widget-builder /widget/dist ./widget/dist",
    ]

    copied_instructions = [
        instruction
        for instruction in runtime.instructions
        if instruction.startswith("COPY ")
    ]
    forbidden_copy_terms = (
        "node_modules",
        "COPY frontend/",
        "COPY widget/",
        "COPY tests",
        "COPY scripts",
    )
    assert all(
        term not in instruction
        for instruction in copied_instructions
        for term in forbidden_copy_terms
    )


def test_python_runtime_excludes_node_and_qa_runtime_payloads() -> None:
    runtime = _docker_stages()[-1]
    runtime_instructions = "\n".join(runtime.instructions).lower()

    assert "node_modules" not in runtime_instructions
    assert "playwright" not in runtime_instructions
    assert "npm " not in runtime_instructions
    assert " node " not in f" {runtime_instructions} "
    assert "copy ." not in runtime_instructions


def test_python_runtime_installs_only_runtime_dependencies() -> None:
    runtime = _docker_stages()[-1]
    instructions = "\n".join(runtime.instructions)

    assert "COPY requirements-runtime.txt ." in runtime.instructions
    assert "pip install --no-cache-dir -r requirements-runtime.txt" in instructions

    requirements = RUNTIME_REQUIREMENTS_PATH.read_text(encoding="utf-8").lower()
    forbidden_qa_distributions = (
        "pytest",
        "pytest-asyncio",
        "ruff",
        "mypy",
        "bandit",
    )
    assert all(name not in requirements for name in forbidden_qa_distributions)


def test_model_cache_is_owned_by_runtime_user_before_user_transition() -> None:
    runtime = _docker_stages()[-1]
    instructions = list(runtime.instructions)
    ownership = next(
        instruction
        for instruction in instructions
        if instruction.startswith("RUN ")
        and "chown -R ragstudio:ragstudio" in instruction
        and "/home/ragstudio/.cache" in instruction
    )

    assert instructions.index(ownership) < instructions.index("USER ragstudio")


def test_python_runtime_retains_operational_container_contract() -> None:
    runtime = _docker_stages()[-1]
    instructions = "\n".join(runtime.instructions)

    assert "TextEmbedding" in instructions
    assert "SparseTextEmbedding" in instructions
    assert "Ranker" in instructions
    assert "USER ragstudio" in runtime.instructions
    assert 'ENTRYPOINT ["/docker-entrypoint.sh"]' in runtime.instructions
    assert "HEALTHCHECK" in instructions
    assert "/health" in instructions


def test_compose_and_template_select_valid_bundled_ui_modes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _compose_service_names() == (
        "rag-studio",
        "rag-studio-saas",
        "stage3-db",
        "stage3-db-bootstrap",
        "stage3-auth",
        "stage3-mail",
        "stage3-fake-deepseek",
        "stage3-qdrant",
    )

    environment = _compose_environment()
    assert "RAG_STUDIO_UI_MODE=legacy" in environment
    assert "RAG_STUDIO_REACT_DIST=/app/frontend/dist" in environment

    template_ui_mode = _environment_template_value("RAG_STUDIO_UI_MODE")
    template_runtime_mode = _environment_template_value("RAG_STUDIO_RUNTIME_MODE")
    assert template_ui_mode == "react"
    assert template_runtime_mode == "saas"

    monkeypatch.setenv("RAG_STUDIO_UI_MODE", template_ui_mode)
    monkeypatch.delenv("RAG_STUDIO_REACT_DIST", raising=False)
    configuration = load_application_ui_configuration(
        RuntimeMode(template_runtime_mode)
    )
    assert configuration.mode is UiMode.REACT

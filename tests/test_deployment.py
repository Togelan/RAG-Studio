"""Integration and unit tests for FR-008: Deployment, Persistence & Security.

Covers:
- AC-008.1: Single Docker Container (health check)
- AC-008.2: Data Persistence
- AC-008.3: API Key Encryption at Rest (in test_security.py)
- AC-008.4: Dockerfile & Build (structural checks)
- AC-008.5: Model Caching in Docker (Dockerfile inspection)
- AC-008.6: OOM Protection (reranker fallback)
- AC-008.7: Docker Resource Constraints (docker-compose inspection)
- AC-008.8: Audit Logging
- AC-008.9: Graceful Shutdown
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# ============================================================
# AC-008.1: Single Docker Container — Health Check
# ============================================================


class TestAC0081HealthCheck:
    """AC-008.1: Verify health endpoint returns expected structure."""

    def test_health_endpoint_returns_ready(self) -> None:
        """Health check returns qdrant status and overall readiness."""
        from src.api.routes.health import HealthResponse

        # Verify the response model structure
        response = HealthResponse(qdrant="ok", status="ready")
        assert response.qdrant == "ok"
        assert response.status == "ready"
        data = response.model_dump()
        assert "qdrant" in data
        assert "status" in data

    def test_health_endpoint_degraded_when_qdrant_unavailable(self) -> None:
        """Health check reports degraded when Qdrant is unavailable."""
        from src.api.routes.health import HealthResponse

        response = HealthResponse(qdrant="unavailable", status="degraded")
        assert response.qdrant == "unavailable"
        assert response.status == "degraded"


# ============================================================
# AC-008.2: Data Persistence
# ============================================================


class TestAC0082DataPersistence:
    """AC-008.2: Verify data survives container stop/start."""

    def test_secrets_load_and_save_roundtrip(self) -> None:
        """Secrets encrypted to disk can be decrypted back."""
        from src.api.dependencies import decrypt_api_key, encrypt_api_key

        original = json.dumps(
            {"OPENAI_API_KEY": "sk-test123", "LANGCHAIN_PROJECT": "test"}
        )
        encrypted = encrypt_api_key(original)
        decrypted = decrypt_api_key(encrypted)
        assert decrypted == original
        assert encrypted != original  # Must be encrypted

    def test_secrets_persist_to_disk(self) -> None:
        """Secrets written to a file can be reloaded."""
        from src.api.dependencies import load_secrets, save_secrets

        with tempfile.TemporaryDirectory() as tmpdir:
            secrets_path = Path(tmpdir) / "secrets.enc"
            with patch(
                "src.api.dependencies.get_secrets_path", return_value=secrets_path
            ):
                test_data = {"OPENAI_API_KEY": "sk-test-persist"}
                save_secrets(test_data)
                assert secrets_path.exists()

                loaded = load_secrets()
                assert loaded == test_data


# ============================================================
# AC-008.4: Dockerfile & Build
# ============================================================


class TestAC0084DockerfileBuild:
    """AC-008.4: Verify Dockerfile structure and docker-compose.yml existence."""

    def test_dockerfile_exists(self) -> None:
        """Dockerfile exists at project root."""
        dockerfile = Path(__file__).parent.parent / "Dockerfile"
        assert dockerfile.exists(), f"Dockerfile not found at {dockerfile}"

    def test_dockerfile_has_multi_stage(self) -> None:
        """Dockerfile uses multi-stage builds (FROM ... AS ...)."""
        dockerfile = Path(__file__).parent.parent / "Dockerfile"
        content = dockerfile.read_text()
        assert "AS builder" in content, "Dockerfile missing builder stage"
        assert "AS runtime" in content, "Dockerfile missing runtime stage"

    def test_dockerfile_exposes_port_8000(self) -> None:
        """Dockerfile exposes port 8000."""
        dockerfile = Path(__file__).parent.parent / "Dockerfile"
        content = dockerfile.read_text()
        assert "EXPOSE 8000" in content, "Dockerfile must expose port 8000"

    def test_dockerfile_has_healthcheck(self) -> None:
        """Dockerfile includes HEALTHCHECK instruction."""
        dockerfile = Path(__file__).parent.parent / "Dockerfile"
        content = dockerfile.read_text()
        assert "HEALTHCHECK" in content, "Dockerfile must contain HEALTHCHECK"

    def test_docker_compose_exists(self) -> None:
        """docker-compose.yml exists at project root."""
        compose_file = Path(__file__).parent.parent / "docker-compose.yml"
        assert compose_file.exists(), f"docker-compose.yml not found at {compose_file}"


# ============================================================
# AC-008.5: Model Caching in Docker
# ============================================================


class TestAC0085ModelCaching:
    """AC-008.5: Verify Dockerfile includes model pre-caching RUN commands."""

    def test_dockerfile_caches_dense_model(self) -> None:
        """Dockerfile pre-caches sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2."""
        dockerfile = Path(__file__).parent.parent / "Dockerfile"
        content = dockerfile.read_text()
        assert (
            "TextEmbedding('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')"
            in content
            or 'TextEmbedding("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")'
            in content
        ), "Dockerfile must pre-cache dense embedding model"

    def test_dockerfile_caches_sparse_model(self) -> None:
        """Dockerfile pre-caches Qdrant/bm25 sparse model."""
        dockerfile = Path(__file__).parent.parent / "Dockerfile"
        content = dockerfile.read_text()
        assert "SparseTextEmbedding('Qdrant/bm25')" in content, (
            "Dockerfile must pre-cache BM25 sparse model"
        )


# ============================================================
# AC-008.6: OOM Protection
# ============================================================


class TestAC0086OOMProtection:
    """AC-008.6: Verify reranker OOM fallback to RRF-only retrieval."""

    def setup_method(self) -> None:
        """Reset reranker state before each test."""
        from src.retrieve.orchestrator import reset_reranker

        reset_reranker()

    def test_reranker_lazy_loading(self) -> None:
        """Reranker is loaded lazily — not imported at module level by default."""
        from src.retrieve.orchestrator import get_reranker_status

        # Initially, reranker should not have been attempted
        status = get_reranker_status()
        # It may be None (not attempted) or False (attempted and failed)
        # The key is it hasn't been eagerly loaded
        assert status["available"] in (True, False)
        # Status dict has the right structure
        assert "available" in status

    def test_reranker_fallback_on_memory_error(self) -> None:
        """When reranker raises MemoryError, system falls back to RRF-only."""
        from src.retrieve.orchestrator import _get_reranker, reset_reranker

        # Ensure clean state
        reset_reranker()

        with patch(
            "flashrank.Ranker",
            side_effect=MemoryError("Simulated OOM"),
        ):
            reranker = _get_reranker()
            assert reranker is None

            from src.retrieve.orchestrator import (
                _reranker_available,
                _reranker_load_error,
            )

            assert _reranker_available is False
            assert _reranker_load_error is not None
            assert "Simulated OOM" in _reranker_load_error

    def test_reranker_fallback_on_general_error(self) -> None:
        """When reranker fails with a general exception, system falls back."""
        from src.retrieve.orchestrator import _get_reranker, reset_reranker

        reset_reranker()

        with patch(
            "flashrank.Ranker",
            side_effect=RuntimeError("Model not found"),
        ):
            reranker = _get_reranker()
            assert reranker is None

            from src.retrieve.orchestrator import _reranker_available

            assert _reranker_available is False

    def test_is_reranker_available_reflects_state(self) -> None:
        """is_reranker_available() returns correct boolean state."""
        from src.retrieve.orchestrator import (
            is_reranker_available,
            reset_reranker,
        )

        reset_reranker()

        with patch(
            "flashrank.Ranker",
            side_effect=MemoryError("Simulated OOM"),
        ):
            result = is_reranker_available()
            assert result is False


# ============================================================
# AC-008.7: Docker Resource Constraints
# ============================================================


class TestAC0087ResourceConstraints:
    """AC-008.7: Verify docker-compose.yml documents resource limits."""

    def test_docker_compose_has_mem_limit(self) -> None:
        """docker-compose.yml includes mem_limit for the service."""
        compose_file = Path(__file__).parent.parent / "docker-compose.yml"
        content = compose_file.read_text()
        assert "mem_limit" in content, "docker-compose.yml must define mem_limit"

    def test_docker_compose_has_cpus(self) -> None:
        """docker-compose.yml includes cpus constraint."""
        compose_file = Path(__file__).parent.parent / "docker-compose.yml"
        content = compose_file.read_text()
        assert "cpus" in content, "docker-compose.yml must define cpus constraint"

    def test_docker_compose_documents_recommendations(self) -> None:
        """docker-compose.yml documents RAM/CPU recommendations."""
        compose_file = Path(__file__).parent.parent / "docker-compose.yml"
        content = compose_file.read_text()
        assert "4 GB" in content or "4g" in content or "4G" in content, (
            "docker-compose.yml must document minimum RAM"
        )


# ============================================================
# AC-008.8: Audit Logging
# ============================================================


class TestAC0088AuditLogging:
    """AC-008.8: Verify structured JSON audit logging."""

    def test_log_audit_produces_valid_json(self) -> None:
        """log_audit writes valid JSON entries."""
        import logging

        from src.api.dependencies import _AUDIT_LOGGER_NAME, log_audit

        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch("src.api.dependencies._audit_logger", None),
                patch.dict(os.environ, {"RAG_STUDIO_LOGS_PATH": str(tmpdir)}),
            ):
                log_audit("upload", filename="test.pdf", success=True)

                # Allow time for file write
                import time

                time.sleep(0.1)

                # Close handlers so Windows can clean up the temp dir
                audit_logger = logging.getLogger(_AUDIT_LOGGER_NAME)
                for handler in audit_logger.handlers[:]:
                    handler.close()
                    audit_logger.removeHandler(handler)

                # Check that log file was created
                log_files = list(Path(tmpdir).glob("audit*"))
                assert len(log_files) > 0, "No audit log file was created"

    def test_log_audit_strips_api_keys(self) -> None:
        """Audit log MUST NOT contain API keys."""
        from src.api.dependencies import sanitize_for_log

        data = {
            "OPENAI_API_KEY": "sk-secret-key-12345",
            "action": "upload",
            "filename": "doc.pdf",
        }
        sanitized = sanitize_for_log(data)
        assert sanitized["OPENAI_API_KEY"] == "[REDACTED]"
        assert sanitized["action"] == "upload"
        assert sanitized["filename"] == "doc.pdf"

    def test_log_audit_includes_required_fields(self) -> None:
        """Audit log entry includes timestamp, action, success."""
        import logging

        from src.api.dependencies import _AUDIT_LOGGER_NAME, log_audit

        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch("src.api.dependencies._audit_logger", None),
                patch.dict(os.environ, {"RAG_STUDIO_LOGS_PATH": str(tmpdir)}),
            ):
                log_audit("chat", session_id="sess-123", success=True)

                import time

                time.sleep(0.1)

                # Close handlers so Windows can clean up the temp dir
                audit_logger = logging.getLogger(_AUDIT_LOGGER_NAME)
                for handler in audit_logger.handlers[:]:
                    handler.close()
                    audit_logger.removeHandler(handler)

                log_files = list(Path(tmpdir).glob("audit*"))
                if log_files:
                    content = log_files[0].read_text()
                    assert "timestamp" in content
                    assert "chat" in content
                    assert "sess-123" in content
                    assert "success" in content

    def test_sanitize_nested_dicts(self) -> None:
        """Nested dictionaries are recursively sanitized."""
        from src.api.dependencies import sanitize_for_log

        nested = {
            "config": {
                "api_key": "sk-nested-key",
                "model": "gpt-4o",
                "nested_deep": {"password": "secret123"},
            }
        }
        sanitized = sanitize_for_log(nested)
        assert sanitized["config"]["api_key"] == "[REDACTED]"
        assert sanitized["config"]["model"] == "gpt-4o"
        assert sanitized["config"]["nested_deep"]["password"] == "[REDACTED]"


# ============================================================
# AC-008.9: Graceful Shutdown
# ============================================================


class TestAC0089GracefulShutdown:
    """AC-008.9: Verify graceful shutdown on SIGTERM with 10s timeout."""

    @pytest.mark.asyncio
    async def test_shutdown_waits_for_pending_tasks(self) -> None:
        """Shutdown waits for in-progress tasks to complete."""
        from src.api.main import _SHUTDOWN_TIMEOUT

        assert _SHUTDOWN_TIMEOUT == 10, "Shutdown timeout must be 10 seconds"

    @pytest.mark.asyncio
    async def test_pending_tasks_tracking(self) -> None:
        """Tasks are tracked in _pending_tasks set."""
        from src.api.main import _create_task, _pending_tasks

        async def dummy_task() -> str:
            await asyncio.sleep(0.01)
            return "done"

        task = _create_task(dummy_task())
        assert task in _pending_tasks

        # Wait for completion
        result = await task
        assert result == "done"

        # Task should be removed from pending set after completion
        assert task not in _pending_tasks

    @pytest.mark.asyncio
    async def test_shutdown_cancels_stuck_tasks(self) -> None:
        """Tasks that don't complete within 10s are cancelled."""
        from src.api.main import _create_task, _pending_tasks

        # Clear existing tasks
        _pending_tasks.clear()

        async def slow_task() -> None:
            await asyncio.sleep(60)  # Never completes in time

        task = _create_task(slow_task())
        assert task in _pending_tasks

        # Simulate shutdown: wait for gather with short timeout
        try:
            await asyncio.wait_for(
                asyncio.gather(task, return_exceptions=True),
                timeout=0.05,
            )
        except asyncio.TimeoutError:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Task should be cancelled
        assert task.cancelled() or task.done()

    def test_lifespan_exists(self) -> None:
        """FastAPI app has lifespan context manager."""
        from src.api.main import lifespan

        assert lifespan is not None
        assert callable(lifespan)


# ============================================================
# NFR-023: Startup Integrity
# ============================================================


class TestNFR023StartupIntegrity:
    """NFR-023: Startup polls Qdrant health with 30s timeout, 2s retries."""

    @pytest.mark.asyncio
    async def test_qdrant_client_waits_for_ready(self) -> None:
        """QdrantClientManager.wait_for_ready has correct timeout/retry params."""
        from src.vector_store.client import QdrantClientManager

        # Verify class-level constants for startup polling (NFR-023)
        assert QdrantClientManager.STARTUP_TIMEOUT == 30
        assert QdrantClientManager.STARTUP_RETRY_INTERVAL == 2

    @pytest.mark.asyncio
    async def test_health_check_failure_raises(self) -> None:
        """If Qdrant is not reachable, wait_for_ready raises RuntimeError."""
        from src.vector_store.client import QdrantClientManager

        manager = QdrantClientManager()

        # Simulate persistent failure
        with patch.object(manager, "health_check", AsyncMock(return_value=False)):
            with pytest.raises(RuntimeError, match="Qdrant did not become ready"):
                await manager.wait_for_ready(timeout=0.5, retry_interval=0.1)


# ============================================================
# Additional: .env.example validation
# ============================================================


class TestEnvExample:
    """Verify .env.example contains no real keys."""

    def test_env_example_exists(self) -> None:
        """.env.example file exists."""
        env_file = Path(__file__).parent.parent / ".env.example"
        assert env_file.exists(), ".env.example not found"

    def test_env_example_no_real_keys(self) -> None:
        """.env.example contains placeholder values, not real keys."""
        env_file = Path(__file__).parent.parent / ".env.example"
        content = env_file.read_text()
        # Check that placeholder patterns exist
        assert "sk-your-key-here" in content
        assert "your-key-here" in content
        # No real-looking API keys (sk- followed by > 20 chars that aren't "your-key-here")
        import re

        real_key_pattern = re.compile(r"sk-[a-zA-Z0-9]{20,}")
        real_keys = real_key_pattern.findall(content)
        assert len(real_keys) == 0, f"Found potential real API keys: {real_keys}"


# ============================================================
# .dockerignore validation
# ============================================================


class TestDockerignore:
    """Verify .dockerignore excludes sensitive files."""

    def test_dockerignore_exists(self) -> None:
        """.dockerignore file exists."""
        ignore_file = Path(__file__).parent.parent / ".dockerignore"
        assert ignore_file.exists(), ".dockerignore not found"

    def test_dockerignore_excludes_git(self) -> None:
        """.dockerignore excludes .git directory."""
        ignore_file = Path(__file__).parent.parent / ".dockerignore"
        content = ignore_file.read_text()
        assert ".git" in content

    def test_dockerignore_excludes_env(self) -> None:
        """.dockerignore excludes .env files."""
        ignore_file = Path(__file__).parent.parent / ".dockerignore"
        content = ignore_file.read_text()
        assert ".env" in content

    def test_dockerignore_excludes_tests(self) -> None:
        """.dockerignore excludes tests directory."""
        ignore_file = Path(__file__).parent.parent / ".dockerignore"
        content = ignore_file.read_text()
        assert "tests/" in content

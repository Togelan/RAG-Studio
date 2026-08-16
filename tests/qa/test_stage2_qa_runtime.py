from __future__ import annotations

import socket
from pathlib import Path

import pytest

from scripts.qa.stage2_qa_runtime import acquire_lease, cleanup_existing


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_lease_uses_and_removes_only_its_marked_root(tmp_path: Path) -> None:
    root = tmp_path / "rag-studio-stage2-qa-cleanup"
    sibling = tmp_path / "keep.txt"
    sibling.write_text("keep", "utf-8")
    lease = acquire_lease(port=_free_port(), root=root, environment={})

    assert lease.root.is_dir()
    assert lease.marker.is_file()
    lease.cleanup()

    assert not root.exists()
    assert sibling.read_text("utf-8") == "keep"


def test_recovery_cleanup_validates_marker_and_writes_receipt(tmp_path: Path) -> None:
    root = tmp_path / "rag-studio-stage2-qa-recovery"
    receipt = tmp_path / "cleanup.json"
    port = _free_port()
    acquire_lease(port=port, root=root, environment={})

    cleanup_existing(root, port, receipt)

    assert not root.exists()
    assert '"root_removed": true' in receipt.read_text("utf-8")


@pytest.mark.parametrize(
    "name", ["OPENAI_API_KEY", "RAG_STUDIO_DATA_ROOT", "QDRANT_URL"]
)
def test_lease_refuses_secret_or_production_environment(
    tmp_path: Path, name: str
) -> None:
    root = tmp_path / f"rag-studio-stage2-qa-{name.lower()}"
    with pytest.raises(RuntimeError, match="refuses populated environment"):
        acquire_lease(port=_free_port(), root=root, environment={name: "set"})
    assert not root.exists()


def test_lease_refuses_production_root_and_port_collision(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="dedicated prefixed"):
        acquire_lease(
            port=_free_port(), root=tmp_path / "production-data", environment={}
        )

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        port = int(listener.getsockname()[1])
        with pytest.raises(RuntimeError, match="already in use"):
            acquire_lease(
                port=port,
                root=tmp_path / "rag-studio-stage2-qa-collision",
                environment={},
            )

"""Guarded launcher for the isolated Stage 2 browser-QA runtime."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import tempfile
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import uvicorn

from scripts.qa.stage2_qa_app import create_qa_app
from scripts.qa.stage2_qa_state import Stage2QaState

type JsonValue = (
    None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_PORTS = frozenset({6333, 8000})
SECRET_ENV = (
    "ANTHROPIC_API_KEY",
    "DEEPSEEK_API_KEY",
    "LANGCHAIN_API_KEY",
    "OPENAI_API_KEY",
    "QDRANT_API_KEY",
)
PRODUCTION_ENV = (
    "RAG_STUDIO_DATA_ROOT",
    "RAG_STUDIO_SETTINGS_PATH",
    "QDRANT_URL",
)


@dataclass(frozen=True, slots=True)
class QaLease:
    """Validated disposable runtime identity."""

    project_id: str
    root: Path
    port: int
    marker: Path

    def cleanup(self) -> None:
        """Remove only a root carrying this lease's exact marker."""
        if not self.marker.is_file():
            raise RuntimeError("QA cleanup marker is missing")
        payload = json.loads(self.marker.read_text("utf-8"))
        if payload != {"project_id": self.project_id, "port": self.port}:
            raise RuntimeError("QA cleanup marker does not match this runtime")
        shutil.rmtree(self.root)


def _environment_guard(environment: dict[str, str]) -> None:
    populated = [
        name
        for name in (*SECRET_ENV, *PRODUCTION_ENV)
        if environment.get(name, "").strip()
    ]
    if populated:
        raise RuntimeError(
            f"isolated QA refuses populated environment: {', '.join(populated)}"
        )


def _port_guard(port: int) -> None:
    if port in FORBIDDEN_PORTS or not 1024 <= port <= 65535:
        raise RuntimeError("isolated QA port is reserved or out of range")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as error:
            raise RuntimeError("isolated QA port is already in use") from error


def _root_guard(root: Path, *, require_empty: bool = True) -> None:
    resolved = root.resolve()
    forbidden = {
        REPO_ROOT.resolve(),
        Path.home().resolve(),
        Path(resolved.anchor).resolve(),
    }
    if resolved in forbidden or not resolved.name.startswith("rag-studio-stage2-qa-"):
        raise RuntimeError("isolated QA root must be a dedicated prefixed directory")
    if require_empty and resolved.exists() and any(resolved.iterdir()):
        raise RuntimeError("isolated QA root must not contain existing data")


def acquire_lease(
    *,
    port: int,
    root: Path | None = None,
    environment: dict[str, str] | None = None,
) -> QaLease:
    """Validate all isolation constraints, then create one disposable lease."""
    _environment_guard(dict(os.environ) if environment is None else environment)
    _port_guard(port)
    project_id = f"rag-studio-stage2-qa-{uuid.uuid4().hex[:8]}"
    if root is None:
        root = Path(tempfile.mkdtemp(prefix="rag-studio-stage2-qa-"))
    else:
        _root_guard(root)
        root.mkdir(parents=False, exist_ok=True)
    _root_guard(root)
    marker = root / ".stage2-qa-lease.json"
    try:
        marker.write_text(json.dumps({"project_id": project_id, "port": port}), "utf-8")
    except OSError:
        if root.exists() and root.name.startswith("rag-studio-stage2-qa-"):
            shutil.rmtree(root)
        raise
    return QaLease(project_id=project_id, root=root, port=port, marker=marker)


def _write_receipt(path: Path | None, payload: dict[str, JsonValue]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), "utf-8")


def cleanup_existing(root: Path, port: int, receipt: Path | None = None) -> None:
    """Recover an interrupted runtime using its exact marker and released port."""
    _root_guard(root, require_empty=False)
    marker = root / ".stage2-qa-lease.json"
    if not marker.is_file():
        raise RuntimeError("QA cleanup marker is missing")
    payload = json.loads(marker.read_text("utf-8"))
    project_id = payload.get("project_id")
    if payload.get("port") != port or not isinstance(project_id, str):
        raise RuntimeError("QA cleanup marker does not match the requested runtime")
    if not _port_is_free(port):
        raise RuntimeError("QA runtime must be stopped before cleanup")
    lease = QaLease(project_id=project_id, root=root, port=port, marker=marker)
    lease.cleanup()
    _write_receipt(
        receipt,
        {
            "cleanup": {"port_released": True, "root_removed": not root.exists()},
            "exit_code": 0,
            "project_id": project_id,
            "recovered_after_interrupt": True,
            "root": str(root),
        },
    )


def serve(port: int, root: Path | None, receipt: Path | None) -> int:
    """Run the credential-free app and always clean its disposable root."""
    lease = acquire_lease(port=port, root=root)
    started = time.monotonic()
    urls: dict[str, JsonValue] = {
        "health": f"http://127.0.0.1:{port}/health",
        "settings": f"http://127.0.0.1:{port}/app/settings",
        "qa_profile": f"http://127.0.0.1:{port}/__qa/profile",
    }
    print(
        json.dumps(
            {"project_id": lease.project_id, "root": str(lease.root), "urls": urls}
        )
    )
    completed = False
    try:
        state = Stage2QaState(lease.project_id, lease.root)
        app = create_qa_app(
            state,
            dist_root=REPO_ROOT / "frontend" / "dist",
            locale_root=REPO_ROOT / "src" / "api" / "locales",
        )
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
        completed = True
    finally:
        lease.cleanup()
        _write_receipt(
            receipt,
            {
                "cleanup": {
                    "port_released": _port_is_free(port),
                    "root_removed": not lease.root.exists(),
                },
                "duration_ms": round((time.monotonic() - started) * 1000),
                "exit_code": 0 if completed else 1,
                "project_id": lease.project_id,
                "root": str(lease.root),
                "urls": urls,
            },
        )
    return 0


def _port_is_free(port: int) -> bool:
    try:
        _port_guard(port)
    except RuntimeError:
        return False
    return True


def build_parser() -> argparse.ArgumentParser:
    """Create the bounded launcher argument parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    serve_parser = subcommands.add_parser("serve")
    serve_parser.add_argument("--port", type=int, required=True)
    serve_parser.add_argument("--root", type=Path)
    serve_parser.add_argument("--receipt", type=Path)
    cleanup_parser = subcommands.add_parser("cleanup")
    cleanup_parser.add_argument("--port", type=int, required=True)
    cleanup_parser.add_argument("--root", type=Path, required=True)
    cleanup_parser.add_argument("--receipt", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Launch the selected isolated-QA command."""
    args = build_parser().parse_args(argv)
    if args.command == "serve":
        return serve(args.port, args.root, args.receipt)
    if args.command == "cleanup":
        cleanup_existing(args.root, args.port, args.receipt)
        return 0
    raise RuntimeError("unsupported command")


if __name__ == "__main__":
    raise SystemExit(main())

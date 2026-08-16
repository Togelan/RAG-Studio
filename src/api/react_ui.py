"""Validated serving primitives for the Stage 2 React cutover.

The module owns the small trust boundary between a Vite build directory and
the FastAPI application.  React mode is only usable after its manifest and
every published asset have been validated as files contained by the selected
distribution directory.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Final

from fastapi import HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from src.paths import resolve_project_path

_UI_MODE_ENV: Final = "RAG_STUDIO_UI_MODE"
_REACT_DIST_ENV: Final = "RAG_STUDIO_REACT_DIST"
_DEFAULT_REACT_DIST: Final = "frontend/dist"
_MANIFEST_RELATIVE_PATH: Final = Path(".vite/manifest.json")
_NO_STORE: Final = "no-store"
_IMMUTABLE_ASSET_CACHE: Final = "public, max-age=31536000, immutable"


class UiMode(StrEnum):
    """Supported canonical page implementations."""

    LEGACY = "legacy"
    REACT = "react"


class InvalidUiModeError(ValueError):
    """Raised when the selected UI mode is not one of the approved values."""


class ReactBuildError(RuntimeError):
    """Raised when the selected React build cannot be served safely."""


class _ViteManifestEntry(BaseModel):
    """The Vite manifest fields that identify publishable files."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    file: str = Field(min_length=1)
    css: tuple[str, ...] = ()
    assets: tuple[str, ...] = ()
    imports: tuple[str, ...] = ()
    dynamic_imports: tuple[str, ...] = Field(default=(), alias="dynamicImports")


_VITE_MANIFEST = TypeAdapter(dict[str, _ViteManifestEntry])


@dataclass(frozen=True, slots=True)
class ReactBuild:
    """A fully validated React distribution that may be exposed to clients."""

    root: Path
    index_path: Path
    manifest_path: Path
    published_assets: Mapping[str, Path]


@dataclass(frozen=True, slots=True)
class UiServingConfiguration:
    """The selected UI mode and any verified React build required by it."""

    mode: UiMode
    react_build: ReactBuild | None


def load_ui_serving_configuration() -> UiServingConfiguration:
    """Read and validate the UI serving configuration from the environment."""
    mode = _parse_ui_mode(os.getenv(_UI_MODE_ENV, UiMode.REACT.value))
    if mode is UiMode.LEGACY:
        return UiServingConfiguration(mode=mode, react_build=None)

    return UiServingConfiguration(mode=mode, react_build=_load_react_build())


def react_document_response(configuration: UiServingConfiguration) -> Response:
    """Return the React HTML document or a sanitized unbuilt-preview response."""
    build = configuration.react_build
    if build is None:
        return Response(
            content="React preview is unavailable until the frontend is built.",
            status_code=503,
            media_type="text/plain",
            headers={"Cache-Control": _NO_STORE},
        )

    return FileResponse(
        path=build.index_path,
        media_type="text/html",
        headers={"Cache-Control": _NO_STORE},
    )


def react_asset_response(
    configuration: UiServingConfiguration,
    asset_path: str,
) -> Response:
    """Return one validated manifest or hashed asset without path traversal."""
    build = configuration.react_build
    if build is None:
        raise HTTPException(status_code=404, detail="Not found")

    if asset_path == _MANIFEST_RELATIVE_PATH.as_posix():
        return FileResponse(
            path=build.manifest_path,
            media_type="application/json",
            headers={"Cache-Control": _NO_STORE},
        )

    asset = build.published_assets.get(asset_path)
    if asset is None:
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(
        path=asset,
        headers={"Cache-Control": _IMMUTABLE_ASSET_CACHE},
    )


def _parse_ui_mode(configured_mode: str) -> UiMode:
    """Parse the closed set of approved UI modes."""
    mode = configured_mode.strip().lower()
    match mode:
        case UiMode.LEGACY.value:
            return UiMode.LEGACY
        case UiMode.REACT.value:
            return UiMode.REACT
        case _:
            raise InvalidUiModeError(
                "RAG_STUDIO_UI_MODE must be either 'legacy' or 'react'."
            )


def _load_react_build() -> ReactBuild:
    """Validate the configured Vite distribution before React mode is enabled."""
    configured_dist = os.getenv(_REACT_DIST_ENV, _DEFAULT_REACT_DIST)
    root = resolve_project_path(configured_dist)
    manifest_path = root / _MANIFEST_RELATIVE_PATH
    index_path = root / "index.html"
    if not root.is_dir() or not index_path.is_file() or not manifest_path.is_file():
        raise ReactBuildError("The selected React UI build is unavailable.")

    try:
        manifest = _VITE_MANIFEST.validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError) as exc:
        raise ReactBuildError("The selected React UI build is invalid.") from exc

    if not manifest:
        raise ReactBuildError("The selected React UI build is invalid.")

    assets: dict[str, Path] = {}
    for entry in manifest.values():
        _validate_import_references(entry, manifest)
        for relative_asset in (entry.file, *entry.css, *entry.assets):
            resolved_asset = _contained_file(root, relative_asset)
            url_path = resolved_asset.relative_to(root).as_posix()
            if not url_path.startswith("assets/"):
                raise ReactBuildError("The selected React UI build is invalid.")
            assets[url_path] = resolved_asset

    return ReactBuild(
        root=root,
        index_path=index_path,
        manifest_path=manifest_path,
        published_assets=MappingProxyType(assets),
    )


def _validate_import_references(
    entry: _ViteManifestEntry,
    manifest: dict[str, _ViteManifestEntry],
) -> None:
    """Ensure Vite import references resolve to manifest entries."""
    for import_name in (*entry.imports, *entry.dynamic_imports):
        if import_name not in manifest:
            raise ReactBuildError("The selected React UI build is invalid.")


def _contained_file(root: Path, relative_asset: str) -> Path:
    """Resolve a manifest asset only when it remains inside *root* and is a file."""
    candidate = (root / relative_asset).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ReactBuildError("The selected React UI build is invalid.") from exc
    if not candidate.is_file():
        raise ReactBuildError("The selected React UI build is invalid.")
    return candidate

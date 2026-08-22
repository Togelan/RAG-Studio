from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.react_ui import ReactBuild, UiMode, UiServingConfiguration
from src.api.routes.ui import create_ui_router


def _react_configuration(tmp_path: Path) -> UiServingConfiguration:
    build_root = tmp_path / "react-dist"
    build_root.mkdir()
    index_path = build_root / "index.html"
    index_path.write_text('<main data-unified-shell="true"></main>', encoding="utf-8")
    return UiServingConfiguration(
        mode=UiMode.REACT,
        react_build=ReactBuild(
            root=build_root,
            index_path=index_path,
            manifest_path=build_root / "manifest.json",
            published_assets=MappingProxyType({}),
        ),
    )


def test_unknown_direct_app_route_serves_react_recovery_document(
    tmp_path: Path,
) -> None:
    app = FastAPI()
    app.include_router(create_ui_router(_react_configuration(tmp_path)))

    with TestClient(app) as client:
        response = client.get("/app/not-a-real-route")

    assert response.status_code == 200
    assert 'data-unified-shell="true"' in response.text
    assert response.headers["cache-control"] == "no-store"


def test_app_spa_fallback_does_not_capture_api_or_legacy_paths(tmp_path: Path) -> None:
    app = FastAPI()
    app.include_router(create_ui_router(_react_configuration(tmp_path)))
    legacy_app = FastAPI()
    legacy_app.include_router(
        create_ui_router(UiServingConfiguration(UiMode.LEGACY, None))
    )

    with TestClient(app) as client:
        api_response = client.get("/api/not-a-real-route")
        legacy_response = client.get("/legacy/not-a-real-route")
    with TestClient(legacy_app) as legacy_client:
        legacy_mode_response = legacy_client.get("/app/not-a-real-route")

    assert api_response.status_code == 404
    assert api_response.json() == {"detail": "Not Found"}
    assert legacy_response.status_code == 404
    assert legacy_mode_response.status_code == 404

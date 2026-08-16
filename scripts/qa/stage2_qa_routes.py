"""Route registrars for the isolated Stage 2 QA FastAPI surface."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Body, FastAPI, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, RootModel

from scripts.qa.stage2_qa_documents import QaCapacityError
from scripts.qa.stage2_qa_schema import LogicalSnapshot, WorkloadProfile
from scripts.qa.stage2_qa_state import Stage2QaState
from scripts.qa.stage2_qa_types import (
    ChunkingSettings,
    ChunksPage,
    DeleteResponse,
    DocumentsPage,
    HealthResponse,
    LoadResponse,
    LocaleResponse,
    ModelsResponse,
    ProgressResponse,
    ReingestResponse,
    SavedSettings,
    SeedDocumentsResponse,
    SettingsPayload,
    SettingsResponse,
    ValidateKeyResponse,
)


class LocaleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    locale: Literal["en", "ru"]


class ChunkingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1]
    strategy: Literal["static", "recursive", "parent_document", "sentence_window"]
    chunk_size: int = Field(ge=128, le=4096)
    chunk_overlap: int = Field(ge=0, le=512)
    parent_size: int | None = Field(default=None, ge=512, le=4096)
    window_sentences: int | None = Field(default=None, ge=1, le=3)

    def to_payload(self) -> ChunkingSettings:
        return {
            "schema_version": self.schema_version,
            "strategy": self.strategy,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "parent_size": self.parent_size,
            "window_sentences": self.window_sentences,
        }


class SettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["deepseek"]
    model: Literal["qa-model"]
    temperature: float = Field(ge=0, le=2)
    max_tokens: int = Field(ge=1, le=32_768)
    system_prompt: str = Field(max_length=20_000)
    top_k: int = Field(ge=1, le=100)
    chunk_size: int = Field(ge=128, le=4096)
    chunk_overlap: int = Field(ge=0, le=512)
    chunking: ChunkingRequest

    def to_payload(self) -> SettingsPayload:
        return {
            "provider": self.provider,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "system_prompt": self.system_prompt,
            "top_k": self.top_k,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "chunking": self.chunking.to_payload(),
        }


class ReingestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    doc_id: str = Field(min_length=1, max_length=80)
    filename: str = Field(min_length=1, max_length=200)


class SeedDocumentsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    count: int = Field(ge=0, le=1000)


async def latency(state: Stage2QaState) -> None:
    await asyncio.sleep(state.workload.latency_ms / 1000)


def safe_error(status: int, detail: str) -> HTTPException:
    return HTTPException(status_code=status, detail=detail)


def register_health_locale(
    app: FastAPI, state: Stage2QaState, locale_root: Path
) -> None:
    @app.get("/health")
    async def health() -> HealthResponse:
        return {
            "status": "ok",
            "mode": "stage2-isolated-qa",
            "project_id": state.project_id,
        }

    @app.post("/api/ui/locale")
    async def set_locale(request: LocaleRequest, response: Response) -> LocaleResponse:
        locale_path = locale_root / f"{request.locale}.json"
        translations = (
            RootModel[dict[str, str]]
            .model_validate_json(locale_path.read_text("utf-8"))
            .root
        )
        response.set_cookie("locale", request.locale, httponly=False, samesite="lax")
        return {"locale": request.locale, "translations": translations}


def register_settings(app: FastAPI, state: Stage2QaState) -> None:
    @app.get("/api/settings")
    async def settings_get() -> SettingsResponse:
        await latency(state)
        return state.settings_response()

    @app.post("/api/settings")
    async def settings_save(
        payload: Annotated[SettingsRequest, Body()],
    ) -> SavedSettings:
        await latency(state)
        return state.save_settings(payload.to_payload())

    @app.get("/api/settings/models/{provider}")
    async def settings_models(provider: str) -> ModelsResponse:
        await latency(state)
        if provider != "deepseek":
            return {
                "provider": provider,
                "models": [],
                "cached": False,
                "error": "Unavailable",
            }
        return {
            "provider": provider,
            "models": ["qa-model"],
            "cached": True,
            "error": None,
        }

    @app.post("/api/settings/validate-key")
    async def validate_key() -> ValidateKeyResponse:
        await latency(state)
        return {
            "valid": False,
            "provider": "deepseek",
            "error": "QA runtime uses no credentials.",
        }


def register_ingestion_reads(app: FastAPI, state: Stage2QaState) -> None:
    @app.get("/api/ingest/documents")
    async def documents(
        cursor: str | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> DocumentsPage:
        await latency(state)
        try:
            return state.list_documents(cursor, limit)
        except ValueError as error:
            raise safe_error(400, "Cursor is invalid.") from error

    @app.get("/api/ingest/documents/{doc_id}/chunks")
    async def chunks(
        doc_id: str,
        cursor: str | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> ChunksPage:
        await latency(state)
        try:
            return state.list_chunks(doc_id, cursor, limit)
        except ValueError as error:
            raise safe_error(400, "Cursor is invalid.") from error
        except KeyError as error:
            raise safe_error(404, "Document was not found.") from error

    @app.get("/api/ingest/progress/{job_id}")
    async def progress(job_id: str) -> ProgressResponse:
        await latency(state)
        try:
            return state.progress(job_id)
        except KeyError as error:
            raise safe_error(404, "Upload was not found.") from error


def register_upload(app: FastAPI, state: Stage2QaState) -> None:
    @app.post("/api/ingest/upload")
    async def upload(
        file: Annotated[UploadFile, File()],
        action: Annotated[
            Literal["default", "cancel", "rename", "replace"], Query()
        ] = "default",
    ) -> JSONResponse:
        await latency(state)
        content = await file.read(50 * 1024 * 1024 + 1)
        if len(content) > 50 * 1024 * 1024:
            raise safe_error(400, "File exceeds the QA limit.")
        filename = file.filename or ""
        if filename.startswith("stage2_sample_upload_fail"):
            raise safe_error(503, "Upload is temporarily unavailable.")
        try:
            status, payload = state.upload(filename, content, action)
        except QaCapacityError as error:
            raise safe_error(
                429, "QA document capacity is temporarily full."
            ) from error
        except ValueError as error:
            raise safe_error(400, "File is not supported.") from error
        return JSONResponse(payload, status_code=status)


def register_ingestion_mutations(app: FastAPI, state: Stage2QaState) -> None:
    @app.post("/api/ingest/reingest", status_code=202)
    async def reingest(request: ReingestRequest) -> ReingestResponse:
        await latency(state)
        try:
            return state.reingest(request.doc_id)
        except KeyError as error:
            raise safe_error(404, "Document was not found.") from error
        except RuntimeError as error:
            raise safe_error(503, "Re-ingestion is temporarily unavailable.") from error

    @app.delete("/api/ingest/documents/{doc_id}")
    async def delete_document(doc_id: str) -> DeleteResponse:
        await latency(state)
        deleted = state.delete(doc_id)
        if not deleted:
            raise safe_error(404, "Document was not found.")
        return {
            "status": "ok",
            "message": "Document deleted.",
            "deleted_count": deleted,
        }

    @app.delete("/api/ingest/clear")
    async def clear_documents() -> DeleteResponse:
        await latency(state)
        deleted = state.clear()
        return {
            "status": "ok",
            "message": "Documents cleared.",
            "deleted_count": deleted,
        }


def register_qa_controls(app: FastAPI, state: Stage2QaState) -> None:
    @app.get("/__qa/profile")
    async def qa_profile() -> WorkloadProfile:
        return state.workload

    @app.get("/__qa/snapshot")
    async def qa_snapshot() -> LogicalSnapshot:
        return state.snapshot()

    @app.post("/__qa/load")
    async def qa_load(snapshot: LogicalSnapshot) -> LoadResponse:
        state.load_snapshot(snapshot)
        return {"status": "ok", "sha256": state.snapshot().sha256(ignore_project=True)}

    @app.post("/__qa/seed-documents")
    async def seed_documents(payload: SeedDocumentsRequest) -> SeedDocumentsResponse:
        return {"status": "ok", "count": state.seed_documents(payload.count)}


def register_spa(app: FastAPI, index_path: Path) -> None:
    @app.get("/{route:path}", response_class=FileResponse)
    async def react_spa(route: str) -> FileResponse:
        if route.startswith(("api/", "__qa/", "react-assets/")):
            raise safe_error(404, "Not found.")
        return FileResponse(index_path)

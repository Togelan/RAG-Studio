"""Tenant-bound text ingestion without legacy global persistence."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Final

from src.api.chunking_settings import ChunkingSettings
from src.ingestion.chunking_dispatch import (
    dispatch_text,
    settings_payload,
    unit_payload,
)
from src.ingestion.embedder import make_doc_id, make_document_doc_id
from src.ingestion.embedding import Embedder
from src.ingestion.parser import canonicalize_filename
from src.ingestion.tenant_uploads import TenantSourceUpload, parse_tenant_source
from src.vector_store.models import DocumentReplacement, VectorRecord
from src.vector_store.tenant_store import TenantRagStore

_MAX_TEXT_CHARACTERS: Final = 5_000_000


class TenantDocumentRejectedError(ValueError):
    """Reject invalid or unbounded SaaS text documents."""


@dataclass(frozen=True, slots=True)
class TenantIngestionResult:
    """Sanitized result of one complete tenant document replacement."""

    doc_id: str
    chunk_count: int


@dataclass(frozen=True, slots=True)
class TenantTextIngestor:
    """Chunk, embed, and atomically replace text in one tenant store."""

    embedder: Embedder
    chunking: ChunkingSettings = field(default_factory=ChunkingSettings)

    async def ingest(
        self, store: TenantRagStore, filename: str, text: str
    ) -> TenantIngestionResult:
        """Ingest validated text without touching legacy files or collections."""
        if not text or len(text) > _MAX_TEXT_CHARACTERS:
            raise TenantDocumentRejectedError("tenant_document_invalid")
        try:
            canonical_filename = canonicalize_filename(filename)
        except ValueError:
            raise TenantDocumentRejectedError("tenant_document_invalid") from None
        doc_id = str(make_document_doc_id(canonical_filename))
        batch = dispatch_text(text, self.chunking, doc_id)
        if not batch.units:
            raise TenantDocumentRejectedError("tenant_document_invalid")
        texts = batch.texts
        dense = self.embedder.embed_dense(texts)
        sparse = self.embedder.embed_sparse(texts)
        created_at = datetime.now(UTC).isoformat()
        records = tuple(
            VectorRecord(
                point_id=make_doc_id(canonical_filename, index),
                dense=dense[index],
                sparse=sparse[index],
                payload=MappingProxyType(
                    {
                        "text": chunk,
                        "source": canonical_filename,
                        "chunk_index": index,
                        "total_chunks": len(texts),
                        "doc_id": doc_id,
                        "created_at": created_at,
                        **unit_payload(batch, batch.units[index]),
                    }
                ),
            )
            for index, chunk in enumerate(texts)
        )
        await store.replace_document(
            DocumentReplacement(
                doc_id=doc_id,
                filename=canonical_filename,
                records=records,
                chunk_size=self.chunking.chunk_size,
                chunk_overlap=self.chunking.chunk_overlap,
                created_at=created_at,
                strategy=batch.strategy,
                schema_version=self.chunking.schema_version,
                file_hash=hashlib.sha256(text.encode()).hexdigest(),
                chunking_fingerprint=self.chunking.fingerprint,
                chunking_settings=settings_payload(self.chunking),
            )
        )
        return TenantIngestionResult(doc_id, len(records))

    async def ingest_source(
        self, store: TenantRagStore, upload: TenantSourceUpload
    ) -> TenantIngestionResult:
        """Parse and atomically replace one tenant source by filename."""
        return await self.ingest(store, upload.filename, parse_tenant_source(upload))

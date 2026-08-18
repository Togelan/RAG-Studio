"""Temporary parsing of one authorized SaaS source upload."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from src.ingestion.parser import detect_and_parse, validate_file


class TenantSourceUploadRejectedError(ValueError):
    """Signal a source that cannot enter the tenant ingestion boundary."""


@dataclass(frozen=True, slots=True)
class TenantSourceUpload:
    """An already-read upload with no persistent local-data ownership."""

    filename: str
    content_type: str | None
    content: bytes


def parse_tenant_source(upload: TenantSourceUpload) -> str:
    """Parse one bounded upload in a temporary server-owned location."""
    try:
        validate_file(upload.filename, len(upload.content), upload.content)
        suffix = Path(upload.filename).suffix
        with TemporaryDirectory(prefix="rag-studio-tenant-") as directory:
            source_path = Path(directory, f"source{suffix}")
            source_path.write_bytes(upload.content)
            text, _ = detect_and_parse(
                source_path, upload.filename, upload.content_type
            )
    except OSError, UnicodeDecodeError, ValueError:
        raise TenantSourceUploadRejectedError("tenant_source_upload_invalid") from None
    if not text.strip():
        raise TenantSourceUploadRejectedError("tenant_source_upload_invalid")
    return text

"""Document ingestion module — upload, parse, chunk, embed.

Exports:
- router: FastAPI APIRouter for ingestion endpoints
- chunk_text: Split text into overlapping chunks
- chunk_csv_rows: Chunk CSV rows
- generate_dense_embeddings: Dense vector generation
- generate_sparse_embeddings: Sparse vector generation
- ensure_collection_exists: Create Qdrant collection
- make_doc_id: UUID5 chunk ID
- make_document_doc_id: UUID5 document ID
- upsert_chunks: Upsert chunks to Qdrant
- validate_file: File validation
- detect_file_type: File type detection
- detect_and_parse: Auto-detect and parse
- parse_txt, parse_pdf, parse_docx, parse_csv, parse_csv_as_rows
- MAX_FILE_SIZE: Maximum file size constant
"""

from src.ingestion.chunker import chunk_csv_rows, chunk_text
from src.ingestion.embedder import (
    ensure_collection_exists,
    generate_dense_embeddings,
    generate_sparse_embeddings,
    make_doc_id,
    make_document_doc_id,
    upsert_chunks,
)
from src.ingestion.parser import (
    MAX_FILE_SIZE,
    detect_and_parse,
    detect_file_type,
    parse_csv,
    parse_csv_as_rows,
    parse_docx,
    parse_pdf,
    parse_txt,
    validate_file,
)
from src.ingestion.router import router

__all__ = [
    "router",
    "chunk_text",
    "chunk_csv_rows",
    "generate_dense_embeddings",
    "generate_sparse_embeddings",
    "ensure_collection_exists",
    "make_doc_id",
    "make_document_doc_id",
    "upsert_chunks",
    "validate_file",
    "detect_file_type",
    "detect_and_parse",
    "parse_txt",
    "parse_pdf",
    "parse_docx",
    "parse_csv",
    "parse_csv_as_rows",
    "MAX_FILE_SIZE",
]

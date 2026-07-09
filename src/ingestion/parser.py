"""Document parser — TXT, MD, PDF, DOCX, CSV.

Supports:
- TXT/MD: plain open() with UTF-8
- PDF: PyPDF2 text extraction (no OCR)
- DOCX: python-docx paragraph extraction
- CSV: stdlib csv, row-by-row with column headers
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Maximum file size for parsing (50 MB)
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

# Supported file extensions
SUPPORTED_EXTENSIONS = frozenset({".txt", ".md", ".pdf", ".docx", ".csv"})

# MIME type to extension mapping (for fallback detection)
_MIME_MAP: dict[str, str] = {
    "text/plain": ".txt",
    "text/markdown": ".md",
    "text/csv": ".csv",
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}


def detect_file_type(filename: str, content_type: str | None = None) -> str:
    """Detect file type from filename extension or content type.

    Args:
        filename: Original filename.
        content_type: MIME type from HTTP upload (optional).

    Returns:
        File extension including dot (e.g., '.pdf').

    Raises:
        ValueError: If file type is not supported.
    """
    # Try extension first
    ext = Path(filename).suffix.lower()
    if ext in SUPPORTED_EXTENSIONS:
        return ext

    # Fallback to content type
    if content_type and content_type in _MIME_MAP:
        ext = _MIME_MAP[content_type]
        if ext in SUPPORTED_EXTENSIONS:
            return ext

    raise ValueError(
        f"Unsupported file type: {filename}. "
        f"Supported formats: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
    )


def parse_txt(file_path: str | Path) -> str:
    """Parse a plain text or Markdown file.

    Args:
        file_path: Path to the .txt or .md file.

    Returns:
        Full text content as a string.
    """
    path = Path(file_path)
    return path.read_text(encoding="utf-8")


def parse_md(file_path: str | Path) -> str:
    """Parse a Markdown file (same as TXT for now).

    Args:
        file_path: Path to the .md file.

    Returns:
        Full Markdown content as a string.
    """
    return parse_txt(file_path)


def parse_pdf(file_path: str | Path) -> str:
    """Parse a PDF file using PyPDF2 (text extraction only, no OCR).

    Args:
        file_path: Path to the .pdf file.

    Returns:
        Extracted text content as a single string.

    Raises:
        ValueError: If the PDF contains no extractable text (scanned/OCR-only).
    """
    from PyPDF2 import PdfReader

    path = Path(file_path)
    reader = PdfReader(str(path))
    pages: list[str] = []

    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text.strip())

    full_text = "\n\n".join(pages)

    if not full_text.strip():
        raise ValueError(
            "No text found in PDF. Scanned/OCR-only PDFs are not supported in this version."
        )

    return full_text


def parse_docx(file_path: str | Path) -> str:
    """Parse a DOCX file, preserving paragraph structure.

    Args:
        file_path: Path to the .docx file.

    Returns:
        Extracted text with paragraphs separated by double newlines.
    """
    from docx import Document

    path = Path(file_path)
    doc = Document(str(path))
    paragraphs: list[str] = []

    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            paragraphs.append(text)

    return "\n\n".join(paragraphs)


def parse_csv(file_path: str | Path) -> list[dict[str, str]]:
    """Parse a CSV file row-by-row, preserving column headers.

    Args:
        file_path: Path to the .csv file.

    Returns:
        List of rows, each as a dict mapping column header to value.

    Raises:
        ValueError: If the CSV file is empty or has no headers.
    """
    path = Path(file_path)
    rows: list[dict[str, str]] = []

    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)

        if reader.fieldnames is None:
            raise ValueError("CSV file has no headers.")

        for row in reader:
            rows.append(dict(row))

    if not rows:
        raise ValueError("CSV file contains no data rows.")

    return rows


def detect_and_parse(
    file_path: str | Path,
    original_filename: str,
    content_type: str | None = None,
) -> tuple[str, str]:
    """Auto-detect file type and apply the correct parser.

    Args:
        file_path: Path to the uploaded file on disk.
        original_filename: Original filename (for extension detection).
        content_type: MIME type from HTTP upload (optional).

    Returns:
        Tuple of (parsed_text, file_extension).

    Raises:
        ValueError: If file type is unsupported or parsing fails.
    """
    ext = detect_file_type(original_filename, content_type)

    if ext in (".txt", ".md"):
        text = parse_txt(file_path)
    elif ext == ".pdf":
        text = parse_pdf(file_path)
    elif ext == ".docx":
        text = parse_docx(file_path)
    elif ext == ".csv":
        # For CSV, convert rows to text representation
        rows = parse_csv(file_path)
        # Convert rows to readable text with headers as context
        headers = list(rows[0].keys())
        lines: list[str] = [f"Columns: {', '.join(headers)}"]
        for i, row in enumerate(rows):
            row_text = " | ".join(f"{k}: {v}" for k, v in row.items())
            lines.append(f"Row {i + 1}: {row_text}")
        text = "\n".join(lines)
    else:
        raise ValueError(f"Unsupported file type: {ext}")

    return text, ext


def parse_csv_as_rows(
    file_path: str | Path,
) -> tuple[list[str], list[dict[str, object]]]:
    """Parse a CSV file and return row texts with column metadata.

    Each row is converted to a text chunk with column headers as metadata.

    Args:
        file_path: Path to the .csv file.

    Returns:
        Tuple of (row_texts, metadata_list) where each metadata dict
        contains the column headers and values for that row.
    """
    path = Path(file_path)
    row_texts: list[str] = []
    metadata_list: list[dict[str, object]] = []

    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)

        if reader.fieldnames is None:
            raise ValueError("CSV file has no headers.")

        headers = list(reader.fieldnames)

        for row in reader:
            row_dict = dict(row)
            # Create a readable text representation
            row_text = " | ".join(f"{k}: {v}" for k, v in row_dict.items())
            row_texts.append(row_text)

            # Store column data as metadata
            meta: dict[str, object] = {
                "csv_headers": headers,
                "csv_row_data": row_dict,
                "row_index": len(row_texts) - 1,
            }
            metadata_list.append(meta)

    if not row_texts:
        raise ValueError("CSV file contains no data rows.")

    return row_texts, metadata_list


def validate_file(
    filename: str,
    file_size: int,
    content: bytes | None = None,
) -> None:
    """Validate a file before ingestion (AC-001.7).

    Checks:
    - File size ≤ 50 MB
    - Not empty (0 bytes)
    - Filename ≤ 200 characters
    - No path traversal in filename

    Args:
        filename: Original filename.
        file_size: File size in bytes.
        content: Raw file content bytes (optional, for empty check).

    Raises:
        ValueError: If validation fails.
    """
    # Size check
    if file_size > MAX_FILE_SIZE:
        raise ValueError("File too large. Maximum size is 50 MB.")

    # Empty file check
    if file_size == 0:
        raise ValueError("Empty file")

    # Filename length check
    if len(filename) > 200:
        raise ValueError("Filename too long. Maximum length is 200 characters.")

    # Path traversal check
    filename_normalized = filename.replace("\\", "/")
    if ".." in filename_normalized.split("/"):
        raise ValueError("Invalid filename")

    # Absolute path check
    if filename.startswith("/") or filename.startswith("\\"):
        raise ValueError("Invalid filename")

    # Drive letter check (Windows absolute path)
    if len(filename) >= 2 and filename[1] == ":":
        raise ValueError("Invalid filename")

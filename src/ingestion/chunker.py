"""Text chunker — recursive character splitting with overlap.

Implements RecursiveCharacterTextSplitter logic:
- Splits on natural separators: \\n\\n, \\n, . , ? , ! , space, char
- chunk_size=512, chunk_overlap=64
- Preserves paragraph/sentence boundaries
- Discards chunks under 20 characters (noise)
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Splitter separators in priority order (most natural first)
_SEPARATORS = ["\n\n", "\n", ". ", "? ", "! ", " ", ""]

# Minimum chunk length (discard shorter chunks as noise)
_MIN_CHUNK_LENGTH = 20


class RecursiveCharacterTextSplitter:
    """Split text into chunks recursively on natural separators.

    Mirrors the langchain RecursiveCharacterTextSplitter algorithm
    but is self-contained with no external dependencies.
    """

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
        separators: list[str] | None = None,
        length_function: Any = len,
    ) -> None:
        """Initialize the splitter.

        Args:
            chunk_size: Maximum characters per chunk.
            chunk_overlap: Number of characters to overlap between chunks.
            separators: List of separators to try, in priority order.
            length_function: Function to measure text length (default: len).
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators if separators is not None else _SEPARATORS
        self.length_function = length_function

    def split_text(self, text: str) -> list[str]:
        """Split text into chunks.

        Args:
            text: The full text to split.

        Returns:
            List of text chunks.
        """
        # First, merge multiple newlines
        text = self._normalize_text(text)
        return self._split_text(text, self.separators)

    def _normalize_text(self, text: str) -> str:
        """Normalize text by collapsing excessive whitespace.

        Args:
            text: Raw text to normalize.

        Returns:
            Normalized text.
        """
        # Replace 3+ newlines with double newlines
        import re

        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _split_text(self, text: str, separators: list[str]) -> list[str]:
        """Recursively split text using the given separators.

        Args:
            text: Text to split.
            separators: List of separators to try (will pop from front).

        Returns:
            List of chunks.
        """
        final_chunks: list[str] = []

        # Find the right separator to use
        separator = separators[-1]  # default to last (character-level)
        new_separators: list[str] = []

        for i, sep in enumerate(separators):
            sep_escaped = sep if sep else ""
            if sep_escaped == "":
                separator = sep
                new_separators = separators[i + 1 :]
                break
            if sep in text:
                separator = sep
                new_separators = separators[i + 1 :]
                break

        # If no separator is found, text is a single chunk candidate
        sep_escaped = separator if separator else ""
        splits = self._split_on_separator(text, separator)

        good_splits: list[str] = []
        new_separators = new_separators if new_separators else [""]

        for s in splits:
            if self.length_function(s) < self.chunk_size:
                good_splits.append(s)
            else:
                if good_splits:
                    merged = self._merge_splits(good_splits, separator, new_separators)
                    final_chunks.extend(merged)
                    good_splits = []
                # Recurse
                if new_separators:
                    final_chunks.extend(self._split_text(s, new_separators))
                else:
                    # Force split by character
                    final_chunks.extend(self._split_text(s, [""]))

        if good_splits:
            merged = self._merge_splits(good_splits, separator, new_separators)
            final_chunks.extend(merged)

        # Filter out empty or too-short chunks
        final_chunks = [
            c.strip()
            for c in final_chunks
            if c.strip() and self.length_function(c.strip()) >= _MIN_CHUNK_LENGTH
        ]

        return final_chunks

    def _split_on_separator(self, text: str, separator: str) -> list[str]:
        """Split text on a separator, keeping the separator if applicable.

        Args:
            text: Text to split.
            separator: Separator string.

        Returns:
            List of text splits.
        """
        if separator:
            return text.split(separator)
        else:
            return list(text)

    def _merge_splits(
        self,
        splits: list[str],
        separator: str,
        next_separators: list[str],
    ) -> list[str]:
        """Merge small splits into chunks up to chunk_size, with overlap.

        Args:
            splits: Small text splits to merge.
            separator: The separator used between splits.
            next_separators: Separators for further splitting if needed.

        Returns:
            List of merged chunks.
        """
        docs: list[str] = []
        current_doc: list[str] = []
        total = 0

        sep_len = self.length_function(separator)

        for d in splits:
            d_len = self.length_function(d)

            if total + d_len + (sep_len if current_doc else 0) > self.chunk_size:
                if current_doc:
                    doc = self._join_docs(current_doc, separator)
                    if doc:
                        docs.append(doc)

                    # Handle overlap: keep trailing text from the current chunk
                # Remove from front until remaining total <= chunk_overlap
                while (
                    current_doc and total > self.chunk_overlap and len(current_doc) > 1
                ):
                    removed_len = self.length_function(current_doc[0])
                    total -= removed_len
                    if len(current_doc) > 1:
                        total -= sep_len
                    current_doc.pop(0)

                # Append the new split to the overlap remainder
                if current_doc:
                    total += sep_len
                current_doc.append(d)
                total += d_len
            else:
                if current_doc:
                    total += sep_len
                current_doc.append(d)
                total += d_len

        if current_doc:
            doc = self._join_docs(current_doc, separator)
            if doc:
                docs.append(doc)

        return docs

    def _join_docs(self, docs: list[str], separator: str) -> str | None:
        """Join document pieces with separator.

        Args:
            docs: List of text pieces.
            separator: Separator to use between pieces.

        Returns:
            Joined text, or None if empty.
        """
        text = separator.join(docs).strip()
        if self.length_function(text) >= _MIN_CHUNK_LENGTH:
            return text
        return None


def chunk_text(
    text: str,
    chunk_size: int = 512,
    chunk_overlap: int = 64,
) -> list[str]:
    """Split text into overlapping chunks.

    Args:
        text: Full document text.
        chunk_size: Maximum characters per chunk (default: 512).
        chunk_overlap: Character overlap between chunks (default: 64, ~10%).

    Returns:
        List of text chunks.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", "? ", "! ", " ", ""],
    )
    chunks = splitter.split_text(text)

    logger.info(
        "Chunked text of length %d into %d chunks (size=%d, overlap=%d)",
        len(text),
        len(chunks),
        chunk_size,
        chunk_overlap,
    )

    return chunks


def chunk_csv_rows(
    row_texts: list[str],
    chunk_size: int = 512,
) -> list[str]:
    """Chunk CSV rows — each row becomes a chunk (no splitting within rows).

    Rows that exceed chunk_size are kept as-is (a single large chunk).
    Multiple small rows are NOT merged — each row is a separate unit.

    Args:
        row_texts: List of row text representations.
        chunk_size: Maximum chunk size (rows below this are kept separate).

    Returns:
        List of row text chunks.
    """
    # CSV rows are atomic — each row is a single chunk
    # Only filter out empty rows
    chunks = [row for row in row_texts if row.strip()]

    logger.info(
        "Prepared %d CSV rows as individual chunks",
        len(chunks),
    )

    return chunks

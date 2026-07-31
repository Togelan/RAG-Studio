---
name: rag-studio-rag
description: Work on RAG-Studio document ingestion, embeddings, Qdrant retrieval, reranking, or LangGraph chat flow. Use for changes under src/ingestion, src/retrieve, src/vector_store, or src/graph; do not use for UI-only changes.
---

# RAG-Studio RAG workflow

Read the relevant implementation and its matching tests before editing.

- Keep document formats aligned with `src/ingestion/parser.py`; it currently handles TXT, Markdown, PDF text extraction, DOCX, and CSV.
- Preserve deterministic document and chunk identifiers, metadata, and collection compatibility when changing ingestion or vector storage.
- Treat unavailable Qdrant, model, or provider services as integration constraints: unit tests should mock them rather than requiring live services.
- For graph changes, preserve the typed state contract and route behavior; update graph tests with the implementation.
- Do not present fixed chunk sizes, retrieval weights, or evaluation scores as universal truths. Change them only when the feature, benchmark, or config justifies it.

Verify the focused test directory first. Run broader tests only when the environment can support them, and report unavailable external dependencies.

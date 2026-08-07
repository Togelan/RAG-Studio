# ADR-0001: Add a global strategy library with mixed-strategy retrieval

- Status: Accepted
- Date: 2026-08-06

## Context

RAG-Studio currently has one recursive separator-aware text splitter, global
`chunk_size`/`chunk_overlap` settings, one local Qdrant collection, and direct
point-text retrieval. The product needs selectable static, recursive,
parent-document, and sentence-window strategies while remaining a
single-container personal application.

## Decision

Add one global chunking strategy setting. The settings UI first selects the
strategy and then reveals bounded strategy-specific parameters. Use the
existing recursive behavior as the default and classify legacy documents with
no strategy metadata as recursive.

Use one searchable Qdrant collection and retain strategy metadata in each point
payload. Mixed-strategy retrieval is supported: a query may retrieve legacy
recursive points and points produced by any new strategy in the same hybrid
search, with strategy-aware expansion before reranking and generation.

- static/recursive: search and return the same bounded chunk;
- parent-document: search sentence children and return a bounded paragraph or
  parent segment, deduplicated by parent identifier;
- sentence-window: search sentence points and expand only within the same
  paragraph, then deduplicate overlapping windows.

CSV remains row-atomic regardless of the selected text strategy. Its payload
records the actual strategy marker `csv_row` and preserves row/header
metadata. Citations carry a source location range when the parser provides
one; otherwise they carry the explicit fallback `location_unavailable` rather
than an invented offset.

Count final deduplicated context units toward `top_k`. Replace documents
individually during re-ingestion and preserve the previous document index when
the replacement fails.

## Alternatives considered

1. Per-document strategy selection. Rejected for version one because it would
   add document-level configuration, more complex duplicate/re-ingestion
   behavior, and additional UI state. Mixed-strategy retrieval still supports
   documents that were indexed under different global settings. Revisit if
   users need to choose a strategy independently for each document.
2. Separate Qdrant collections for parents, children, or each strategy.
   Rejected because the local application does not need collection-level
   isolation and extra collections add synchronization and migration failure
   modes. Revisit if payload duplication or mixed-index performance is measured
   to be a bottleneck.
3. Model-backed semantic sentence segmentation. Rejected initially because
   the application already carries local embedding and reranker models, but a
   second NLP model would increase image size, memory, and startup cost. Revisit
   if evaluation shows deterministic segmentation is materially inadequate.

## Consequences

The design preserves the existing Qdrant boundary and local deployment model,
but adds strategy-aware metadata, mixed-strategy expansion, deduplication, and
conditional UI validation. Parent text duplication is bounded by parent-size
presets. Sentence and parent expansion must enforce hard character/context
limits. CSV's actual strategy is `csv_row`, and unavailable parser locations
are represented as `location_unavailable`.

The 50,000-point benchmark is informational evidence under the actual Compose
limits of 4 GB memory and 2 CPU cores. It measures the local profile's
ingestion, memory, storage, retrieval, and failure behavior; it is not a
universal SLA or a hard pass/fail requirement.

The actual Qdrant version upgrade is deliberately separate from this feature.
The verified official release available during design was Qdrant 1.18.1; the
project should pin and test its client/runtime compatibility rather than rely
on an unbounded dependency range.

## Safety and rollback

Legacy flat settings remain readable through a migration adapter. Existing
points are not rebuilt solely to add metadata. Per-document replacement keeps
the prior point set on parse, embedding, disk, or resource failure. A feature
rollback can disable new strategy selection while leaving existing payloads
and the current recursive path intact.

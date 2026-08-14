# RAG-Studio architectural context

## Product boundary

RAG-Studio currently runs as a single-container, local-first personal RAG
application. The approved product target is a locally runnable, hosting-ready
multi-tenant SaaS: React/TypeScript/Tailwind/shadcn frontend, FastAPI BFF and
RAG backend, Supabase-managed identity and organization data, Stripe test-mode
billing, and an embeddable Shadow-DOM widget. The legacy Jinja UI remains only
until its approved replacement is implemented.

The first delivery must run locally on the developer's computer while keeping
configuration environment-driven and deployable later. Do not automatically
migrate existing local documents, vectors, settings, or API keys; the SaaS
starts with empty workspaces and explicit user-controlled imports.

## SaaS terminology and boundaries

- **Workspace**: one company tenant. It owns a separate Qdrant collection,
  documents, chatbots, public widget credentials, and billing entitlement.
- **Membership**: a Supabase-backed association between a user and workspace
  with exactly one launch role: `owner`, `admin`, or `member`.
- **Owner**: manages billing, deletion, ownership transfer, and memberships.
  **Admin**: manages sources, chatbot/widget settings, and invitations.
  **Member**: may use and test chatbots but may not upload, delete, or
  re-index company knowledge.
- **FastAPI BFF**: the sole trusted API boundary for the SaaS frontend and
  widget. It validates identity, membership, role, entitlement, limits,
  widget origin, and workspace-to-collection mapping before any privileged
  operation.
- **Public widget key**: a non-secret identifier for one workspace/chatbot.
  FastAPI enforces its approved-origin allowlist, rate limits, and only then
  resolves the workspace collection. `localhost` is permitted only in
  development.
- **UI workflow**: every UI task follows
  `design-system-style-intelligence → frontend-design-director →
  react-shadcn-ui-contract → omo:visual-qa`.
- **Delivery sequence**: Stage 1 is the completed chunking-strategy baseline;
  Stage 2 migrates the existing working UI to React without inventing future
  SaaS behavior; Stage 3 adds the capabilities required by `migration.md`.
  Every planned task must cite its owning FR and any existing FRs it modifies.
- **UI reference location**: user-provided reference images belong under
  `docs/design/references/saas-ui/` and are recorded in `DESIGN.md` before UI
  implementation.
- **Approved visual direction**: `DESIGN.md` defines the dark-first knowledge
  workspace system: top navigation, neutral navy surfaces, restrained gold for
  primary emphasis, blue-violet only for AI/interactive states, rare
  marketing-only serif emphasis, and functional motion. The legacy
  orange/purple design is removed only after verified React parity preserves a
  rollback path.
- **Browser completion gate**: every implementation must be exercised through
  the running web application with the in-app `@Browser` after automated
  checks pass. Backend-only changes use the closest affected web journey that
  consumes the changed behavior. Completion evidence records the URL,
  scenario, observed result, viewport where relevant, and screenshots for
  visual changes.

## Chunking terminology

- **Static**: fixed character boundaries with configured overlap; no semantic
  separator selection.
- **Recursive**: the existing separator-aware splitter using paragraph,
  newline, sentence, space, and character fallbacks. This is the legacy
  default behavior.
- **Parent document**: sentence children are embedded and searched; the
  containing paragraph or bounded parent segment is returned. Child and parent
  metadata are retained together.
- **Sentence window**: sentence-level points are searched and expanded to a
  bounded set of neighboring sentences within the same paragraph.
- **Context unit**: the final deduplicated text passed to the LLM. `top_k`
  counts context units, not raw child points.

## Ownership and boundaries

`src/ingestion/` owns parsing, strategy selection, chunk formation, and
strategy metadata. `src/api/routes/settings.py` owns the persisted global
chunking configuration. `src/api/templates/settings.html` and the settings
JavaScript own conditional strategy controls. `src/vector_store/` owns Qdrant
translation, payload persistence, and bounded search. `src/retrieve/` owns
strategy-aware expansion, deduplication, reranking input, and final context
limits.

## Stable decisions

- Strategy selection is global for the project, not per document.
- Changing strategy keeps the existing FR-010 Skip/Re-ingest All behavior.
- Re-ingestion should replace documents one at a time without clearing the
  existing index first; failed documents retain their prior index.
- Existing documents without a strategy field are treated as legacy
  `recursive` and are migrated lazily.
- Static, recursive, and parent-document size controls use characters.
  Sentence-window controls use sentence counts.
- CSV files remain row-based and retain their current row metadata regardless
  of the selected text strategy.
- Strategy-specific settings are stored under a nested `chunking` object.
- The default strategy is `recursive`.
- Parent-document defaults are child `512` chars, child overlap `64`, parent
  `2048` chars. Sentence-window default is `±2` sentences. All controls are
  bounded presets.
- The document table exposes each document's actual strategy and parameters.
- Citations describe the final expanded context and preserve source/location
  ranges.

## Operational target

The host profile may provide Docker Desktop with 6 GB available memory, 4 CPU
cores, and at least 10 GB free disk; those host values are context only and are
not the benchmark or acceptance profile. The benchmark and operational target
are the Compose-limited service profile enforced by `docker-compose.yml`: 4 GB
memory and 2 CPU cores, with at least 10 GB free disk. Under that Compose
profile, the 50,000 indexed-point benchmark is informational, with p95
retrieval below 3 seconds reported where the machine and corpus permit;
memory, ingestion duration, and failure behavior are measured rather than
assumed.

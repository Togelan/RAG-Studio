# Graph Guide

## Overview

`src/graph/` owns the LangGraph state machine, provider boundary, retries,
stream normalization, checkpoint-backed sessions, and chat result contracts.

## Where to look

| Task | Location | Notes |
| --- | --- | --- |
| Topology/compilation | `builder.py` | Seven nodes plus checkpointer lifecycle. |
| State contract | `state.py` | `RAGState` keys shared by every node. |
| Node behavior | `nodes.py` | Analysis, retrieval, generation, validation, cache. |
| Provider selection | `llm_provider.py` | Environment/settings to provider adapter. |
| Retry boundary | `retry.py` | Three attempts, jitter, 15-second deadline. |
| Session persistence | `session.py` | Checkpoint CRUD and typed persistence failures. |

## Conventions

- Keep topology: analyzer → cache/retrieve → generation → validate → cache/end.
- Build uncompiled graphs in `build_rag_graph`; own checkpointer resources only
  through the `create_graph` async context manager.
- Inject provider factories, embedders, and vector-store protocols; do not
  resolve FastAPI dependencies inside graph code.
- Keep state updates compatible with `RAGState`; normalize result/citation
  payloads before they cross into API streaming.
- Provider retries stop at the deadline. Once a stream emitted a token, surface
  a typed terminal failure rather than replaying partial output.
- Persist checkpoints through `src.paths`; preserve async cancellation during
  graph, provider, and session operations.

## Anti-patterns

- Never expose raw provider exceptions, prompts, document text, or secret values.
- Do not reorder validation/cache edges without updating routing tests and the
  streaming contract.
- Do not swallow `CancelledError`, convert session failures to success, or use
  an unbounded provider call/retry.
- Keep HTTP status/SSE translation in `src/api`, not in graph modules.

## Verification focus

Run `pytest tests/graph tests/api/test_chat_reliability.py
tests/api/test_chat_streaming.py tests/e2e/test_rag_pipeline.py -v` as applicable.
Cover topology, state defaults, retry exhaustion, partial-stream failure,
checkpoint cleanup, cancellation, citations, and sanitized error codes.

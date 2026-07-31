---
name: rag-studio-delivery
description: Plan or implement a bounded RAG-Studio feature from a functional requirement or user story. Use when a task needs acceptance criteria, a small implementation plan, focused tests, and a concise handoff.
---

# RAG-Studio delivery workflow

Translate the request into observable acceptance criteria. Identify the smallest set of implementation and test files, then make one coherent vertical slice.

- Do not rely on named local subagents, `@skill` aliases, `graphify`, or a particular model: they are not guaranteed to be installed in Codex.
- Delegate only independent, bounded work; otherwise keep the task in one chat to avoid coordination overhead.
- Add or update focused tests for behavior that changes. A test maps to an acceptance criterion when that makes the requirement clearer, but one test does not need to represent exactly one criterion.
- Give a handoff with changed files, verification actually run, and any remaining external dependency or assumption.

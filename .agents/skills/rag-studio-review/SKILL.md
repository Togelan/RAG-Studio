---
name: rag-studio-review
description: Review a RAG-Studio diff for correctness, regressions, security, test coverage, and project conventions. Use only for review requests; do not edit files unless the user asks to address findings.
---

# RAG-Studio code review

Review the requested Git scope first. If none is given, ask whether to review uncommitted changes, a commit, or a branch; in the Codex app, `/review` offers these scopes without modifying the worktree.

Prioritize actionable defects:

1. User-visible behavior regressions and API contract breaks.
2. Security issues, including secret exposure, auth/session isolation, upload validation, and unsafe path handling.
3. Async resource leaks, persistence/data-loss risks, and error-handling gaps.
4. Missing or misleading tests for changed behavior.
5. Consistency with the module’s existing patterns and `AGENTS.md`.

Report only findings that are supported by the diff and name the affected file and line. Separate blocking defects from optional improvements. Do not require live LangSmith/RAGAS runs for a normal code review.

---
name: feature-discussion
description: Run a repository-grounded, one-question-at-a-time architecture discussion for non-trivial feature requests such as “I want to add ...”. Use before implementation to challenge assumptions, capture approved design decisions in CONTEXT.md, docs/adr/, and docs/features/<feature-slug>.md, then stop for explicit approval before handing off to executable planning.
---

# Feature Discussion

Use this skill when the user proposes adding a feature or making a material
architectural change. It is a design gate, not an implementation workflow.

## Scope gate

Use the full discussion for new capabilities, cross-module changes, public API
or data-contract changes, authentication or authorization changes, migrations,
concurrency or load-sensitive work, external integrations, and other changes
that are costly or difficult to reverse.

Do not trigger it for typo fixes, formatting, simple renames, or isolated
one-line bug fixes unless the user explicitly asks for an architecture
discussion. For those tasks, follow the normal project workflow.

## Documentation companion

This skill combines the repository workflow below with the documentation-first
behavior of `grill-with-docs`.

- If `grill-with-docs` is already installed and discoverable, use it as a
  companion for its documentation-first repository inspection and decision
  capture. Keep this skill's one-question-at-a-time and approval rules in
  force if the two instructions differ.
- Do not install packages or run `npx skills@latest add ...` automatically.
  Installation is an explicit environment setup action; if the companion is
  unavailable, continue with this skill's self-contained workflow.
- Treat `CONTEXT.md`, `docs/adr/`, and `docs/features/` as the durable project
  documentation surface. Do not create an ADR for a routine, reversible choice.

## Start with repository evidence

Before asking anything, inspect the actual current checkout. Read `AGENTS.md`,
`.agents/copilot-instructions.md`, relevant `.agents/agents/` guidance,
`system_spec.md`, `README.md`, existing `CONTEXT.md`, `docs/`, configuration,
the relevant source modules and tests, and the current Git status. Search for
existing terminology, entities, routes, schemas, migrations, policies,
observability, and neighboring features. Use only the current checkout; never
use stale branches, worktrees, cached session memory, or invented architecture
as evidence.

Record what is known, what is unknown, and which questions are genuine owner
decisions. Do not ask questions answerable from repository evidence.

## Discussion protocol

When the user says “I want to add [feature description]”:

1. Restate the feature outcome and summarize the relevant repository evidence.
2. Identify the smallest set of unresolved decisions needed to produce an
   approved design.
3. Ask exactly one question. Stop and wait for the user's answer before asking
   another question. Never bundle questions, even when they are related.
4. For every question, include all of the following in concise prose:
   - why the decision matters;
   - the recommended answer;
   - realistic alternatives;
   - trade-offs and consequences;
   - comparison with the current codebase;
   - security, performance, and maintenance risks.
5. Challenge an answer when it conflicts with existing boundaries, contracts,
   security rules, load limits, or project conventions. Explain the conflict
   and ask one focused follow-up question if a decision remains unresolved.
6. Prefer the simplest architecture that satisfies the requirements and can
   evolve later. Do not invent services, databases, queues, abstractions, or
   microservices without repository or requirement evidence.
7. Do not write application code, tests, migrations, or implementation plans
   during this discussion. Documentation is written only after consensus.

Use repository facts to settle defaults. Surface an owner decision when it is
irreversible, safety-critical, externally visible, data-destructive, or a
cross-cutting product choice. Keep a running decision log in the conversation
until the user and agent reach general consensus.

## Required investigation checklist

Before declaring consensus, investigate and record the applicable findings for:

- business requirements, acceptance behavior, non-goals, and domain entities;
- ownership, bounded contexts, module boundaries, and each layer's
  responsibility;
- request and data flow, API contracts, schema, and migrations;
- backward compatibility, authentication, authorization, and input validation;
- security threats, abuse cases, sensitive-data handling, and secret/error
  redaction;
- expected traffic, heavy-load behavior, bottlenecks, capacity limits,
  caching, queues, rate limiting, and concurrency;
- timeouts, retries, fallbacks, cancellation, failure behavior, idempotency,
  and duplicate side effects;
- logging, metrics, tracing, alerts, and operational ownership;
- unit, integration, end-to-end, and manual testing;
- deployment, rollback, migration safety, CI/CD impact, and stack
  compatibility.

If an item does not apply, state why. If the repository cannot answer it, make
the uncertainty explicit and ask about it one question at a time rather than
guessing.

## Consensus documents

When the discussion reaches general consensus, create or update these files
only, in this order:

1. `CONTEXT.md`: stable domain terminology, ownership, boundaries, and
   architectural context. Preserve unrelated existing context.
2. `docs/adr/`: one concise ADR per important or difficult-to-reverse decision.
   Include status, context, decision, alternatives, consequences, and revisit
   conditions. Do not create ADRs for every implementation detail.
3. `docs/features/<feature-slug>.md`: the approved feature design.

The feature design must contain these headings and concrete, repository-grounded
content:

1. Problem statement
2. Requirements and non-goals
3. Current architecture and request flow
4. Proposed architecture
5. Domain model and ownership
6. Files/modules likely to change
7. API and database changes
8. Security analysis
9. Scalability and heavy-load analysis
10. Error-handling strategy
11. Observability strategy
12. Testing strategy
13. Migration and rollback plan
14. Unresolved assumptions
15. Explicit acceptance criteria
16. Manual testing scenarios

Include measured or testable load assumptions, bounded failure behavior, at
least two considered alternatives with rejection and revisit criteria, and
safety evidence covering data preservation, secret/error redaction,
cancellation, and rollback. Mark unknowns as unresolved instead of presenting
them as facts.

## Approval and handoff

After writing the documents, stop and wait for the user's explicit approval.
Do not automatically start executable planning, implementation, a developer,
or a QA workflow.

After the user approves, explain that the feature document is input to
executable planning through the globally installed `alexey-workflow` skill.
That plan must propose an Execution Intensity for every executable task and
model-reasoning final gate; human approval locks them before execution. This
skill ends before planning and must not commit or modify production code.

## Resources (optional)

Create only the resource directories this skill actually needs. Delete this section if no resources are required.

### scripts/
Executable code (Python/Bash/etc.) that can be run directly to perform specific operations.

**Examples from other skills:**
- PDF skill: `fill_fillable_fields.py`, `extract_form_field_info.py` - utilities for PDF manipulation
- DOCX skill: `document.py`, `utilities.py` - Python modules for document processing

**Appropriate for:** Python scripts, shell scripts, or any executable code that performs automation, data processing, or specific operations.

**Note:** Scripts may be executed without loading into context, but can still be read by Codex for patching or environment adjustments.

### references/
Documentation and reference material intended to be loaded into context to inform Codex's process and thinking.

**Examples from other skills:**
- Product management: `communication.md`, `context_building.md` - detailed workflow guides
- BigQuery: API reference documentation and query examples
- Finance: Schema documentation, company policies

**Appropriate for:** In-depth documentation, API references, database schemas, comprehensive guides, or any detailed information that Codex should reference while working.

### assets/
Files not intended to be loaded into context, but rather used within the output Codex produces.

**Examples from other skills:**
- Brand styling: PowerPoint template files (.pptx), logo files
- Frontend builder: HTML/React boilerplate project directories
- Typography: Font files (.ttf, .woff2)

**Appropriate for:** Templates, boilerplate code, document templates, images, icons, fonts, or any files meant to be copied or used in the final output.

---

**Not every skill requires all three types of resources.**

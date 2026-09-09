# Documentation Guide

## Authority

Use the narrowest authoritative document for the decision:

1. `system_spec.md` — functional requirements and Gherkin acceptance criteria.
2. `CONTEXT.md` and accepted ADRs — vocabulary, architecture, and durable decisions.
3. `docs/features/` — scoped designs, ownership, file plans, and acceptance mapping.
4. `docs/deployment/` — executable operations, evidence, rollback, and cleanup.
5. `DESIGN.md` and `docs/design/references/` — normative visual contract and research.

## Where To Look

| Change | Update |
| --- | --- |
| Functional behavior | Owning FR in `system_spec.md`; cite it in the feature doc. |
| Difficult-to-reverse architecture | New or updated accepted ADR. |
| Feature implementation scope | `docs/features/<slug>.md`. |
| Local hosting/QA procedure | `docs/deployment/`. |
| UI tokens/interaction | `DESIGN.md`; references do not override it. |

## Conventions

- Feature docs identify modified FRs, non-goals, ownership, likely files,
  security, scale, failure, observability, tests, migration, rollback, and
  concrete acceptance/manual scenarios.
- ADRs record status/date/scope, context, decision, alternatives and rejection
  reasons, consequences, safety, rollback, and revisit conditions.
- Deployment runbooks include prerequisites, exact commands, bounded failure,
  persistence preservation, backup/restore, cleanup scope, and rollback.
- Deferred capabilities must be named as deferred; documentation must not imply
  unimplemented billing, publication, or SaaS authority.

## Anti-patterns

- Do not duplicate the functional source of truth or silently change an FR in a
  feature/ADR document.
- Never include secrets, cookies, raw user/provider data, filesystem paths, or
  unsanitized QA receipts in committed evidence.
- Do not prescribe destructive Docker cleanup or schema rollback without an
  explicit, project-scoped safety procedure.
- Do not treat design research/reference images as normative implementation rules.

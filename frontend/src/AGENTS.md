# Frontend Source Guide

## Scope

`frontend/src/` is the typed client composition and feature layer. Keep
cross-feature primitives small and keep domain behavior in its feature folder.

## Where To Look

| Area | Rule |
| --- | --- |
| `main.tsx`, `App.tsx` | Own bootstrap, route table, and compatibility redirects. |
| `app/` | Locale/runtime providers and client-wide contracts. |
| `api/` | Transport, CSRF, SSE parsing, abort, and sanitized HTTP errors. |
| `components/shell/` | Shared navigation, account context, and responsive layout. |
| `components/ui/` | Reusable shadcn/Radix-style primitives only. |
| `features/` | Feature pages, local state, API gateways, and feature tests. |
| `i18n/` | Locale inventory, runtime selection, and translated copy. |

## Conventions

- Prefer explicit typed gateways with Zod response schemas and dependency
  injection. Keep request paths and response contracts close to their feature.
- Canonical authenticated pages live under `/app/*`; redirects preserve old
  `/saas/*`, `/settings`, and `/chat` entry points during migration.
- Use semantic status/permission text, keyboard-accessible controls, and locale
  keys for every user-facing string.
- Keep effects cancellable and guard async state updates after unmount or stale
  workspace/session changes.

## Anti-patterns

- Never infer account, workspace role, entitlement, or publication authority from
  browser state. Treat client identifiers as selectors only.
- Do not bypass `src/api/client.ts`, disable CSRF/error validation, or expose raw
  response bodies and provider details.
- Do not use `dangerouslySetInnerHTML`, direct HTML insertion, or color alone to
  communicate state. Preserve the design-system contract in `DESIGN.md`.
- Do not place reusable UI or backend logic in a feature merely to avoid a
  well-defined shared boundary.

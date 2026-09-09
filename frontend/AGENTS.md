# Frontend Agent Guide

## Scope

`frontend/` is an independent React/Vite runtime for the SaaS migration. It
does not own Python routes, persistence, or the legacy Jinja implementation.

## Structure

| Area | Owns |
| --- | --- |
| `src/main.tsx`, `src/App.tsx` | Browser bootstrap, router, compatibility redirects |
| `src/api/` | Typed HTTP, CSRF, streaming, and error contracts |
| `src/components/` | Shared shell and shadcn-style primitives |
| `src/features/` | Domain pages, gateways, and feature state |
| `src/i18n/` | Locale runtime and translated copy |
| `tests/e2e/` | Playwright browser journeys and accessibility/performance tags |
| `scripts/` | Build-output audits and frontend-only checks |

## Where To Look

| Task | Location | Notes |
| --- | --- | --- |
| Route composition | `src/App.tsx` | `/app/*` is canonical; old paths redirect. |
| Authenticated shell | `src/features/saas/SaasEntry.tsx`, `src/components/shell/` | Session and responsive shell boundary. |
| Workspace page dispatch | `src/features/saas/CanonicalWorkspaceContent.tsx` | Server-backed workspace/role selection. |
| API integration | Feature-local `*-api.ts`, `src/api/client.ts` | Gateways validate responses and accept injection for tests. |
| Visual contract | `DESIGN.md`, `src/styles.css` | Design stages precede UI changes. |

## Conventions

- Runtime composition is `main.tsx → App → routes → SaasEntry → AppShell →
  CanonicalWorkspaceContent → feature page`.
- Use Node `24.19.0` and npm `11.17.0`; Vite serves production assets from
  `/react-assets/` and emits a manifest.
- Biome owns formatting/linting: two spaces, double quotes, no semicolons,
  strict unused checks, and no explicit `any` or non-null assertions.
- Keep feature gateways beside their feature. Inject gateways and fake backends
  at composition points instead of coupling tests to network calls.
- Preserve locale parity, responsive shell behavior, focus/keyboard semantics,
  abort signals, and sanitized API errors.

## Anti-patterns

- Do not treat route params, local state, or query strings as authorization or
  billing authority; the API resolves identity and entitlements.
- Never use unsafe HTML insertion in the React surface or store credentials,
  private tokens, or raw provider errors in browser state.
- Do not remove compatibility redirects or legacy rollback routes before parity
  evidence exists.
- Do not add backend Python code, generated `dist/`, or QA state under `frontend/`.

## Commands

```powershell
npm ci
npm run lint
npm run typecheck
npm run test
npm run build
npm run test:e2e
npm run test:a11y
npm run test:perf
npm run audit:prod
```

Playwright is one-worker, cross-browser, and normally uses the deterministic
fake backend. Retain its failure evidence and record URL, scenario, viewport,
and screenshots for visual changes.

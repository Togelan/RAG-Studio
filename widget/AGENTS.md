# Widget Agent Guide

## Scope

`widget/` is an independent private npm package. Its public deliverable is the
single versioned IIFE `dist/rag-studio-widget.v1.js`, not the React application.

## Where To Look

| Task | Location | Notes |
| --- | --- | --- |
| Package entry | `src/index.ts` | Registers `rag-studio-widget`. |
| Element lifecycle | `src/widget-element.ts` | Shadow DOM, focus, layout, and actions. |
| Public transport | `src/public-transport.ts` | Proof, SSE, cancellation, timeout, retry. |
| Markup/theme | `src/widget-template.ts`, `src/widget-styles.ts` | Host isolation and semantic tokens. |
| Embedding contract | `README.md`, `fixtures/` | Approved, hostile, and rejected hosts. |
| Artifact contract | `tests/artifact.test.ts` | Loads the built bundle and checks registration. |

## Conventions

- Use Node `24.19.0` and npm `11.17.0`. Vite emits one minified IIFE named
  `RagStudioWidgetV1`, with no sourcemap and the fixed filename above.
- The widget accepts only documented public attributes. `widget-key` is an
  identifier, never a credential; use `credentials: "omit"` on every request.
- Keep proof schema validation, exact-origin binding, bounded proof refresh,
  strict SSE state transitions, 10-second control timeout, and 60-second stream
  timeout.
- Preserve text-node rendering, Shadow DOM isolation, reduced-motion behavior,
  proof-bound cancellation, sanitized errors, and host CSS containment.
- Changes to public proof/stream/cancel behavior require corresponding backend
  contract tests under `tests/api/`.

## Anti-patterns

- Never import the React app, private API clients, cookies, credentials, user
  state, secrets, browser storage, or private session identifiers.
- Do not broaden publication beyond the allowlisted artifact or introduce
  wildcard/attacker-controlled CORS, HTML injection, unbounded retries, or raw
  server errors.
- Do not treat `dist/` as source; rebuild and run the artifact test after changes.

## Commands

```powershell
npm ci
npm run verify
```

`verify` runs Biome, strict typecheck, non-artifact tests, build, and artifact
validation in order.

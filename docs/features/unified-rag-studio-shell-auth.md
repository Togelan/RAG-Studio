# Unified RAG-Studio shell and route compatibility (FR-021)

**Status:** Group 1 design and compatibility contract. It authorizes no runtime
change by itself.

**Owns:** FR-021’s Group 1 shell cutover contract. It modifies no product
behavior and does not close future owning FRs.

## Evidence basis

The baseline was directly reconciled from the checked-out route and shell
sources, not from a previous report. The captured inventory is
`.omo/evidence/group-1-unified-rag-studio-shell-auth/task-2/baseline-route-inventory.md`.

At baseline, `frontend/src/App.tsx` provides the React entry/alias routes and
passes `/saas/*` into `SaasEntry`; `SaasEntry` can mount a separate `SaasShell`.
`src/api/routes/ui.py` explicitly serves `/legacy`, `/legacy/settings`, and
`/legacy/chat`. `RAG_STUDIO_UI_MODE` is the existing validated `react|legacy`
selection. The current separate SaaS shell and catch-all-to-Welcome behavior
are migration inputs, not target behavior.

## Shell contract

`/app` is the canonical authenticated RAG-Studio route. `/` is the public
access entry: recover the session and render either a minimal public
authentication surface or `/app`; it cannot introduce an alternate brand,
route model, or shell. `/sign-in` and `/sign-up` are equivalent public access
routes for their explicit form modes. After cutover, every authenticated
product route is a descendant of one `AppShell`; `SaasShell` is not mounted in
the user path.

### Approved public-access information architecture — 2026-08-20

Before authentication, the user is not inside RAG-Studio. Public routes use a
`PublicAuthShell`, not `AppShell`: product identity, locale control, concise
factual description, and the single credential task are visible. Application
navigation (Home, Settings, Chat, and Workspace destinations), connection
status, page eyebrow/title, Account/Workspace controls, role, user menu, and
mobile application drawer are absent. They are neither displayed nor rendered
as disabled controls.

An unauthenticated request for `/app` or a descendant is preserved only as an
in-memory allow-listed pathname. Query text, invitation bearers, Account,
Workspace, role, and external targets are discarded; after successful sign-in
the safe path is restored once, otherwise `/app` is used. Confirmation,
service failure, and signed-out states stay on the same public boundary with
sanitized recovery copy. An optional quiet `About RAG-Studio` text link may be
added only when it contains truthful content; it is not a top-navigation tab.
Long-form marketing, pricing, or visual effects remain FR-018 work.

The single top navigation contains only operational Group 1 destinations:

- Home/Personal Lab entry, Chat, and Settings for the local personal surface.
- Chatbots, Sources, and People only for a selected Workspace and only where
  the authenticated effective role permits the real destination.

Knowledge, Agents, Widget Bots, Usage, Billing, profile management, and any
other unimplemented destination are omitted. A disabled-looking, hidden, or
“coming soon” link is not a route and must not appear as a substitute.

The header’s controls are labelled in both English and Russian: `Account`,
`Personal Lab` or `Workspace`, user identity, locale, and `Sign out`. A selected
Workspace also exposes the server-confirmed effective role as text plus semantic
colour: Owner, Admin, or Member. Personal Lab has no invented Workspace role.
The Account/context controls are not a second navigation system and must not
accept a browser-provided Account, Workspace, or role as authority.

### States and disclosure

Before child data renders, the shell has an explicit initial-loading state while
the BFF confirms the session and Account/context. A context switch clears the
previous Workspace and Agent content before displaying the confirmed next
selection. Required localized outcomes are:

| State | Required visible result | Unsafe result prohibited |
| --- | --- | --- |
| Unauthenticated / signed out | Minimal public sign-in/sign-up state with no app navigation or page heading | Prior workspace content, a token error, or disabled-looking product navigation |
| Confirmation required | Recoverable confirmation instruction | A fake authenticated workspace |
| No context / empty | Personal Lab entry or create/select context action only when backed by the BFF | A guessed first Account or Workspace |
| Selection pending | Labelled pending state; duplicate changes prevented | Old child data treated as the selected context |
| Recoverable service error | Sanitized retry/recovery message | Raw transport/provider/database text |
| Forbidden | Permission explanation naming the unavailable task | Disabled-looking mutation controls that imply it may work |
| Revoked, archived, or unavailable | Stale data cleared; a safe available-context choice or sign-in action | Prior Workspace/Agent resources, IDs, or cached role |
| Owner/admin/member | Only real actions for the confirmed effective role | Client role authorization or fabricated controls |

Owner capability is limited to real ownership/membership lifecycle work; admin
capability is limited to the available invitation, source, and chatbot
management work; a member retains authorized chatbot/test use and sees a plain
permission explanation for mutations. User controls are only locale, visible
identity, and sign-out until a feature supplies further behavior.

### Responsive, language, and accessibility contract

| Target | EN/RU layout outcome | Interaction outcome |
| --- | --- | --- |
| 360 px | Compact header; one-column body; labels and long Russian names wrap without action clipping | A labelled 44 px menu opens the single navigation drawer; context control remains labelled and touch-safe |
| 768 px | Header becomes compact before controls collide; contextual regions stack | Drawer keyboard focus is managed and returns to the trigger after close; no horizontal primary-surface scrolling |
| 1440 px | One persistent top bar and bounded content body | Account, context, role, user, and primary navigation are visible without duplicate rail/nav |

All controls use semantic HTML, accessible names, visible `--rs-focus` focus,
WCAG AA text/surface contrast, and `prefers-reduced-motion` behavior. The drawer
is the only mobile navigation surface; it closes on selection or Escape and
restores focus. It does not duplicate hidden focusable links. The existing
dark-first tokens remain authoritative: layered navy surfaces, restrained gold
for a single primary emphasis, blue-violet only for interactive/AI state, and
functional motion.

## Retired `/saas` compatibility matrix — FR021-COMPAT-ROUTE-MATRIX

This is exhaustive for the currently observable `/saas` grammar. The first
column records the baseline behavior; the target column is the canonical Group
1 result to implement in route/UI integration work. `:workspaceId`,
`:chatbotId`, and `:invitationId` are server-validated opaque identifiers; they
are never trusted merely because they appear in a path.

| Retired route/pattern | Baseline current route result | Canonical destination/outcome after cutover | Context and authorization rule |
| --- | --- | --- | --- |
| `/saas` | `SaasEntry`; auth or workspace start | `/` | Recover session; render public authentication or confirmed Account/context, never a second shell |
| `/saas/sign-in` | Caught by `/saas/*`; current auth mode defaults to sign-in | `/sign-in` | Discard prior protected view; no token/state in URL |
| `/saas/sign-up` | Caught by `/saas/*`; no dedicated route-mode parser | `/sign-up` | Confirmation-required remains recoverable; no authenticated context is assumed |
| `/saas/invitations/accept` | Dedicated acceptance page | `/app/invitations/accept` | Requires signed-in identity; accepted membership is reloaded from BFF before selection |
| `/saas/invitations/accept?token=<bearer>` | Current query prepopulates the token field | `/app/invitations/accept` with one-time token intake | Do not echo, log, persist, or retain the bearer in navigation/history UI; sanitize invalid/expired token to recoverable acceptance failure |
| `/saas/invitations/accept?token=` or malformed/expired token | Same acceptance page receives an empty or invalid field value | `/app/invitations/accept` | Remain in the labelled recovery form with sanitized failure; do not reveal whether a token, invitee, or Workspace exists |
| `/saas/workspaces/:workspaceId/people` | `PeoplePage` is selected by substring match | `/app/workspaces/:workspaceId/people` | Preserve only a BFF-confirmed selected Workspace; owner/admin see their real controls, member receives forbidden explanation |
| `/saas/workspaces/:workspaceId/sources` | `SourcesPage` is selected by substring match | `/app/workspaces/:workspaceId/sources` | Preserve only confirmed context; owner/admin manage sources, member gets permission explanation and no mutation control |
| `/saas/workspaces/:workspaceId/chatbots` | Falls through to `ChatbotsPage` | `/app/workspaces/:workspaceId/chatbots` | Preserve only confirmed context; role governs management, while member retains authorized read/test access |
| `/saas/workspaces/:workspaceId/chatbots/new` | Falls through to list; editor is a dialog, not a deep route | `/app/workspaces/:workspaceId/chatbots/new` only when route-addressable editor is implemented | Owner/admin only; until then sanitize to the canonical chatbot list with no fake editor |
| `/saas/workspaces/:workspaceId/chatbots/:chatbotId/edit` | Falls through to list; editor is a dialog | `/app/workspaces/:workspaceId/chatbots/:chatbotId/edit` only when route-addressable editor is implemented | Resolve chatbot in the confirmed Workspace and role-check before display; otherwise recoverable not-found/forbidden |
| `/saas/workspaces/:workspaceId/chatbots/:chatbotId/test` | Falls through to list; test surface is a dialog | `/app/workspaces/:workspaceId/chatbots/:chatbotId/test` only when route-addressable test is implemented | Resolve enabled chatbot in confirmed Workspace; member use is allowed when backend authorizes it; disabled chatbot explains why test cannot start |
| `/saas/workspaces/:workspaceId/chatbots/:chatbotId/test?session=<id>` | No URL-session parser | Same test route only when a server-authorized session deep link exists | Unknown query keys are discarded; invalid/foreign session produces sanitized recovery and cannot reveal transcript data |
| `/saas/workspaces/:workspaceId/chatbots?status=<value>` | Chatbot list ignores the query | `/app/workspaces/:workspaceId/chatbots` | Accept only a documented, server-safe list filter when its owner implements it; otherwise drop the key without changing resource visibility |
| `/saas/workspaces/:workspaceId/sources?sort=<value>` | Sources page ignores the query | `/app/workspaces/:workspaceId/sources` | Drop unsupported sort/filter keys; they cannot access foreign sources or alter the confirmed Workspace |
| `/saas/workspaces/:workspaceId/people?tab=members` and other non-contract query strings | Substring route selection ignores query | Corresponding canonical route with unsupported query dropped | Query strings cannot change role, Account, Workspace, chatbot, or protected view authorization |
| `/saas/workspaces/:workspaceId/...` with malformed, unknown, foreign, revoked, or archived ID | Current shell relies on active session context rather than path validation | `/app/not-found` or `/app` context recovery inside `AppShell` | Clear stale child content first; use sanitized “unavailable”/“no access” copy, never raw UUID/API text |
| `/saas/workspaces/:workspaceId/chatbots/:chatbotId/...` with malformed, unknown, foreign, or disabled chatbot ID | Current fall-through list does not parse the ID | Canonical chatbot list, test-disabled state, or `/app/not-found` according to BFF result | No resource metadata or session content leaks before BFF validation |
| Any other `/saas/*` | `/saas/*` catch-all enters `SaasEntry` and commonly reaches chatbot list | `/app/not-found` rendered inside the sole shell | Sanitized recoverable unknown-route outcome, not Welcome and not a separate SaaS shell |
| `/legacy`, `/legacy/settings`, `/legacy/chat` | Explicit Jinja aliases in FastAPI | Remain the same explicit rollback routes | See rollback contract below; never silently redirect to a dead/static page |

### Invalid, unauthorized, and query behavior — FR021-COMPAT-INVALID-AUTH

Route migration is a compatibility translation, not a client-side authorization
mechanism. A valid deep link carries forward the selected context only when the
BFF revalidates the identity, Account membership, Workspace status, effective
role, and resource relationship before any downstream data/provider work. A
malformed or unknown ID maps to an in-shell, sanitized not-found/recovery
outcome. A valid-but-forbidden/foreign ID maps to an in-shell permission or
context-recovery outcome. A revoked or archived selection additionally clears
prior child state before any replacement content. None of these outcomes use
Welcome as a catch-all, disclose raw IDs, policy internals, provider/database
errors, bearer tokens, or old resources.

Only a documented route-specific query may be consumed. Invitation bearer input
is one-time, never displayed after submission, never placed in logs/evidence,
and not copied into canonical navigation. All other unsupported query keys are
dropped; they cannot select Account/Workspace, choose a role, create a resource,
or make a future route appear implemented.

## Legacy rollback contract — FR021-COMPAT-LEGACY-ROLLBACK

`/legacy`, `/legacy/settings`, and `/legacy/chat` remain explicit, functional
rollback routes until later FR parity and removal gates pass. The existing
`RAG_STUDIO_UI_MODE=legacy` mode is the configuration selector; the Group 1
integration must ensure that selecting it registers the legacy local APIs and
storage used by those pages. A rollback route that serves only HTML, lacks its
local API/storage boundary, or uses the unified Account/Workspace context as a
substitute is a failed rollback.

The rollback switch is operationally reversible: select the validated legacy
mode, restart through the documented runtime flow, and verify the exact
`/legacy`, `/legacy/settings`, and `/legacy/chat` journeys against legacy local
data. It must preserve existing local documents, vectors, settings, provider
configuration, and chat behavior; it must not auto-import any of them into a
Workspace. If the legacy dependencies cannot be registered, startup/config
validation fails safely rather than exposing a decorative fallback. React mode
does not delete the routes or their supporting code.

## Decision record

The selected design reuses the approved dark knowledge-workspace reference
grammar already catalogued in `DESIGN.md`: compact top-bar density and context
from `dashboard.png`, grouped controls from `settings.png`, and cited task
focus from `embed chat.png`. It uses no copied brand/logo/copy/analytics and
keeps the calm dark-first semantic tokens rather than minting a SaaS identity.

| Alternative | Rejected because | Revisit only when |
| --- | --- | --- |
| Keep `SaasShell` and `AppShell` as parallel product shells | Fails FR-021’s one product/navigation/account-context requirement and leaves deep-link meaning ambiguous | Never for the user path; a separately isolated admin product would require a new FR and architecture decision |
| Expose every FR-021 named destination as disabled or “coming soon” navigation | Misrepresents unavailable behavior and violates the no-fake-control boundary | The owning FR supplies a real route, data contract, role policy, and verification |
| Redirect every retired route to `/app` or Welcome | Loses authorized context and turns invalid/unknown routes into misleading success | Only if a future contract proves the old route has no resource/context semantics |

Data preservation is explicit: route translation never migrates local data and
rollback retains it. Security handling is explicit: BFF revalidation precedes
protected rendering and failure text/token values are sanitized. Context changes
and route changes abort or clear dependent work before stale data renders;
rollback is the reversible escape path.

## Manual QA: document-to-current-route reconciliation — FR021-COMPAT-MANUAL-QA

This documentation task has no runtime resource. Its manual QA channel is a
direct reconciliation of every baseline route row with this compatibility
matrix, performed from the current source files named in the Evidence basis.
It is binary: each baseline route/pattern must have exactly one canonical
destination/outcome and exactly one context/authorization rule; any missing,
duplicated, or un-sanitized row fails the contract.

| QA row group | Route rows reconciled | Required binary observable |
| --- | --- | --- |
| Personal entry | `/`, `/app`, settings, chat aliases | One `AppShell` target and no second brand/navigation |
| Retired auth/invitation | `/saas`, sign-in, sign-up, invitation including token query | One canonical auth/acceptance outcome; bearer redaction stated |
| Workspace resources | people, sources, chatbot list, new, edit, test, test session query | A unique canonical mapping or truthful unavailable outcome plus BFF context rule |
| Failure mapping | malformed/unknown/foreign/revoked/archived IDs and unknown `/saas/*` | Sanitized in-shell recovery; no Welcome/raw error/stale resource result |
| Rollback | all three `/legacy` aliases and UI mode | Functional local API/storage rollback requirement, preserved data, safe failure |
| Responsive/localized shell | EN/RU at 360, 768, 1440 | One nav/drawer, labelled controls, role/state, focus, and no horizontal overflow rule |

The post-change structural check names these contract markers and must pass;
the baseline inventory and red-check receipt are retained in the task evidence
directory. Browser screenshots are deliberately not claimed here: this task
changes documentation only and starts no application. The future UI executor
must run the in-app Browser and `omo:visual-qa` against the real implementation
at the six locale/viewport combinations.

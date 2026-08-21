# RAG-Studio Design System

> **Status:** Approved visual direction for the React SaaS migration.
> **Scope:** This is a design contract, not UI implementation or permission to introduce Stage 3 behavior before its owning functional requirement.

## Design thesis

RAG-Studio is a **dark knowledge workspace**: calm, precise, evidence-first, and premium through discipline rather than spectacle. The landing page may be editorial and atmospheric; the application must be quieter, with strong hierarchy, semantic surfaces, reliable states, citations, and clear workspace context.

The product must not resemble a crypto dashboard, gaming interface, neon AI demo, generic purple-gradient SaaS template, or over-decorated glass UI.

## Reference inventory

| Reference | Governs | Reusable evidence | Exclusions |
|---|---|---|---|
| [`main.png`](docs/design/references/saas-ui/main.png) | Marketing composition | Editorial headline, dark product mockup, restrained gold CTA, ambient depth | Third-party logos, unsupported claims, exact copy, and unimplemented features |
| [`dashboard.png`](docs/design/references/saas-ui/dashboard.png) | Application density and top navigation | Compact top bar, workspace context, quiet status panels, clear primary action | Its analytics, quality scores, knowledge-health data, and future navigation items |
| [`settings.png`](docs/design/references/saas-ui/settings.png) | Form hierarchy | Grouped controls, visible labels, segmented choices, live preview, stable save action | Assistant configuration before FR-015 and widget configuration before FR-016 |
| [`embed chat.png`](docs/design/references/saas-ui/embed%20chat.png) | Widget composition | Focused support chat, suggested questions, source chips, launcher/window hierarchy | Host-page copy, avatar artwork, and behavior before FR-016 |
| [`deep-research-report.md`](docs/design/references/design-effects/deep-research-report.md) | Effects, motion, accessibility, and performance | Meaningful states, limited atmosphere, real progress/streaming, widget isolation | Its initial light-mode recommendation, superseded by approved dark-first direction |

References are evidence, never a license to copy brands, logos, copy, imagery, or data. Future SaaS screenshots guide visual language only; they do not add functional scope.

## Stable visual decisions

- Launch is **dark-first**. A light mode is outside the initial migration.
- Desktop navigation is a persistent **top application bar**. The Stage 2 shell starts with Home, Dashboard, Chat, and Settings. Future destinations are grouped instead of extending an unbounded flat tab row.
- On compact widths, the top bar becomes a compact header and accessible navigation drawer.
- Gold is a restrained premium accent: one primary CTA or selected high-value detail at a time, never pervasive decoration or a default panel color.
- Blue-violet indicates AI and interactive state. It is not a general branding color and never replaces semantic success, warning, or error states.
- A serif may highlight one or a few words in a marketing headline. All product UI, long headings, controls, data, chat, and widget content use the primary sans-serif.
- Motion is functional only. It communicates feedback, progress, state, or overlay hierarchy.
- The former orange/purple-gradient identity, background image, breathing counters, and legacy visual assets are removed from the visible product during verified React cutover. Legacy Jinja routes may exist only as a temporary rollback path until their React replacements pass parity and Browser verification.

## Tokens

Use semantic CSS variables mapped to Tailwind and shadcn. Do not scatter raw colors through components.

| Token | Value | Use |
|---|---:|---|
| `--rs-canvas` | `#080C14` | Page and app background |
| `--rs-surface` | `#0E1522` | Standard panel/card |
| `--rs-surface-raised` | `#131D2D` | Grouped controls/elevated regions |
| `--rs-surface-overlay` | `#19263A` | Menus, dialogs, widget overlay |
| `--rs-text` | `#F5F7FB` | Primary text |
| `--rs-text-muted` | `#A6B2C4` | Supporting text and metadata |
| `--rs-border` | `#27364C` | Hairline surface border |
| `--rs-border-strong` | `#43546E` | Controls and selected edge |
| `--rs-gold` | `#E8BC70` | Primary CTA and rare premium emphasis |
| `--rs-gold-ink` | `#1B1307` | Text/icon on gold CTA |
| `--rs-ai` | `#9390FF` | AI stream, active AI control, widget interaction |
| `--rs-success` | `#4BCB8B` | Success state with text/icon |
| `--rs-warning` | `#E3AE57` | Warning state with text/icon |
| `--rs-danger` | `#F07878` | Error/destructive state with text/icon |
| `--rs-focus` | `#B4B2FF` | Keyboard focus ring |
| `--rs-layout-workspace` | `1280px` | FR-012 Chat workspace outer content width |
| `--rs-layout-bottom-nav-reserve` | `76px` | Compact fixed navigation clearance |
| `--rs-layout-loading-block` | `120px` | Minimum Settings loading-skeleton block height |
| `--rs-layout-progress` | `200px` | Inline ingestion upload-progress width |

All final text/color pairs must meet WCAG AA. Use surface contrast and 1px borders to separate persistent areas; reserve shadows for real overlays.

### Typography and geometry

- UI sans: a licensed, performant variable font with English and Russian Cyrillic coverage, with `system-ui` fallback. Select the exact font only after licensing, glyph, and WOFF2 performance checks.
- Editorial serif: marketing-only and loaded only where necessary after English/Russian coverage is verified.
- Mono: technical values, IDs, limits, and code-like data only.
- Body: 14–16px / 1.45–1.55. Source content: 16–18px / 1.5–1.65. App H1: 28–32px. Marketing H1: 56–72px desktop, 38–44px mobile.
- Spacing scale: `4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80, 96` px.
- Radius: 6px dense controls; 8px buttons/inputs; 10–12px cards/popovers; 14–16px dialogs/marketing panels. Avoid universal large-radius cards.
- Content width: 1200–1440px; reading/forms: 640–760px; chat answer measure: about 68–76 characters.

- FR-012 Chat workspace: use `--rs-layout-workspace` for the 1280px outer content width; keep the answer column constrained to the 68–76 character reading measure rather than stretching prose across the workspace.

## Layout and components

### Application shell

The desktop top bar contains product identity, primary navigation, contextual search/command entry when implemented, and account controls. It must not display fake working Stage 3 destinations. The active route has a readable label, a subtle surface or underline change, and a non-color cue where practical. A workspace switcher appears only with real FR-013 workspace context.

### Surfaces, status, forms, and data

- Cards group a meaningful task, not every adjacent block. Default card: surface, 1px border, 10–12px radius, no shadow.
- Design default, hover, focus, active, disabled, loading, empty, error, success, offline, and permission-denied states with the happy path.
- Labels stay visible; placeholders never replace labels. Field order is label, control, then helper/error.
- Segmented controls serve a small mutually exclusive choice set. Save/cancel outcomes remain visible; destructive actions are separated and explicitly confirmed.
- Charts are allowed only for real trends/comparisons. Avoid decorative charts and identical KPI-card grids.

### Chat, citations, and ingestion

- User messages appear immediately. Assistant output streams real backend chunks, supports Stop, and exposes partial-response errors without fake waiting.
- Citations are first-class: source title, stable identifier, location or an explicit unavailable state, snippet, and available action. Desktop may use a source inspector; mobile uses a bottom sheet or full-screen view.
- Ingestion stages are named: Queued, Uploading, Extracting, Preparing, Indexing, Ready, Failed. A percentage is shown only when the backend can calculate it.
- Do not force auto-scroll while a person reads earlier chat content.

### Widget

The widget is a separate Shadow-DOM interface. It owns its styles and exposes only semantic theming tokens such as accent, surface, text, radius, and font. It must not rely on host Tailwind, host typography, global portals, ambient glow, or backdrop blur. On mobile it becomes inset or full-screen rather than a cramped desktop window.

## Effects and motion

**Use frequently:** hairline borders, semantic layered surfaces, visible focus/hover/pressed feedback, real status transitions, skeletons, real ingestion progress, and real AI streaming.

**Use sparingly:** one static radial gradient, 1–2% grain, an ambient glow, a gradient fragment in a marketing headline, static dot/grid texture, translucent landing navigation, or a small marketing reveal.

**Do not use:** animated knowledge networks, persistent aurora, large canvas/WebGL effects, pervasive glassmorphism, neon/chromatic effects, parallax inside the app, fake typewriter output, fake progress, fake AI waiting, confetti, or hover-only essential controls.

Motion tokens: press 80ms; fast 120ms; controls 160ms; overlays 180–220ms; dialogs 220–260ms; layout 240–300ms. Routine application animation must not exceed 400ms. Prefer `opacity` and `transform`; respect `prefers-reduced-motion` with instant changes or short opacity feedback.

## Responsive, accessibility, and performance

- Support 360px and above with no unintended horizontal overflow.
- The desktop top bar becomes a compact header plus an accessible drawer on tablet/mobile. Data-heavy tables have record, sheet, or detail alternatives instead of hidden horizontal scrolling.
- Every control has visible keyboard focus and a 44px minimum effective mobile target. Icon-only controls have accessible names. Dialogs manage focus and include accessible titles.
- Do not announce each streamed token through ARIA live regions. Progress exposes semantic progress/status information.
- Limit WOFF2 font files and weights, lazy-load non-critical UI, and keep the widget bundle stricter than the app bundle.
- Backdrop blur is permitted only for a small isolated marketing or floating layer after performance verification, with an opaque fallback.

## Stage 3 authenticated workspace journeys (FR-013 through FR-015)

### Product job, people, and visual thesis

The primary job is to let a company user enter one trusted workspace, understand
their effective role, and move a chatbot from configuration to a cited test
answer without losing tenant context. Owners need unmistakable control over
membership, transfer, and archive; admins need efficient invitation and chatbot
management; members need a calm, permission-honest test surface with no dead or
misleading controls.

The Stage 3 application stays operational and evidence-first. It extends the
compact workspace selector and quiet status-panel grammar from `dashboard.png`,
the grouped form and preview hierarchy from `settings.png`, and the citation-chip
anatomy from `embed chat.png`. It does not copy their invented analytics, widget
controls, avatars, or brand content. The signature moment is functional: when a
workspace changes, the contextual shell and dependent content settle together
after the server confirms the selection, so the active tenant is always visually
and behaviorally aligned.

### Information hierarchy and screen inventory

1. **Authentication (`/saas/sign-in`, `/saas/sign-up`)**: product identity,
   recoverable credential form, submit state, field validation, sanitized service
   failure, and confirmation-required outcome. Authentication cookies and CSRF
   mechanics remain below the component boundary; no token or secret is rendered
   or stored by application state.
2. **Workspace start (`/saas`)**: current workspace and role first, then the
   chatbot list and its primary allowed action. With no memberships, workspace
   creation is the sole primary task. A lost, revoked, or archived selection
   clears dependent content and returns to a recoverable workspace choice.
3. **People and invitations (`/saas/workspaces/:workspaceId/people`)**: members
   and invitations are separate, labelled regions. Owner-only membership and
   transfer controls are separated from owner/admin invitation controls.
   Invitation acceptance is a signed-in route with one visible token field that
   can be populated from the local inbox link; the bearer value is never echoed
   after submission.
4. **Sources (`/saas/workspaces/:workspaceId/sources`)**: workspace-scoped source
   library with upload, replacement by filename, document readiness metadata, and
   confirmed removal. Owners and admins see upload and remove actions; members see
   a plain permission explanation rather than inactive mutation controls. The
   upload field accepts only supported document files, names the selected source,
   and replaces its idle action with an explicit Uploading state. Re-uploading the
   same filename explains that it atomically replaces only that workspace's source.
5. **Chatbots (`/saas/workspaces/:workspaceId/chatbots`)**: enabled and disabled
   chatbots form one scan-friendly list with localized name, provider/model,
   lifecycle status, and one clear test action. Owner/admin management actions are
   absent for members, not merely disabled.
6. **Chatbot editor (`/saas/workspaces/:workspaceId/chatbots/new` and
   `.../:chatbotId/edit`)**: localized names and instructions, provider/model,
   immutable workspace-wide source scope, field errors, save state, and explicit
   version-conflict recovery. Editing uses the grouped form hierarchy of
   `settings.png`; no unsupported widget configuration appears.
7. **Chatbot test (`/saas/workspaces/:workspaceId/chatbots/:chatbotId/test`)**:
   session list, transcript, composer, stop/reattach affordance, cited sources,
   and feedback. Disabled chatbots explain why a new test cannot start. Partial
   output remains readable after a sanitized stream failure.

### Responsive composition and scroll ownership

- At `1440x900`, the authenticated shell keeps the top bar and workspace selector
  persistent. Workspace lists use a narrow contextual rail only when it improves
  scanning; the page body is the sole scroll owner and reading columns remain
  bounded.
- At `768x1024`, contextual rails become stacked sections or drawers. Two-column
  forms collapse before labels or controls become cramped; confirmation dialogs
  keep actions in predictable document order.
- At `360x800`, the compact header exposes navigation and workspace selection as
  labelled 44px controls. Lists become records, action clusters wrap, forms use
  one column, citations open below the answer, and the composer reserves safe-area
  clearance. No primary surface owns horizontal scrolling.
- Shells use a bounded `auto minmax(0, 1fr)` grid when a fixed region surrounds a
  scroll body. Intrinsic grids use `minmax(min(16rem, 100%), 1fr)` so long names,
  URLs, UUIDs, and Russian copy cannot force overflow.

### Reusable Stage 3 primitives and states

- **AuthCard**: sign-in/sign-up mode, visible labels, password guidance,
  submitting, validation, confirmation-required, expired-session, and service
  error states.
- **WorkspaceSwitcher**: loading, no memberships, selected, selection pending,
  selection rejected, revoked/archived, and keyboard-open states. It never treats
  a browser-provided workspace ID as authority.
- **RoleBadge / PermissionNotice**: owner, admin, and member semantics pair text
  with color. Permission denial identifies the unavailable task without exposing
  policy internals or raw API detail.
- **ResourceList / ResourceRecord**: loading skeleton, empty, populated, disabled,
  stale, and contextual error variants for workspaces, invitations, members,
  chatbots, and sessions. Stable identifiers key every record.
- **SourceLibrary**: upload-ready, uploading, upload-failed, empty, populated,
  replacing, and confirmed-delete states. File input remains labelled and visible;
  source rows use filename, readiness metadata, and a textual action rather than
  opaque icon-only controls.
- **AsyncAction**: idle, pressed, pending, success, recoverable failure, disabled,
  and conflict states. A pending label or progress cue replaces the idle label;
  duplicate submission is prevented without hiding the action.
- **ConfirmActionDialog**: explicit object name, consequence, cancel, and one
  destructive action. Ownership transfer names the receiving member; workspace
  archive and chatbot deletion never imply that knowledge is deleted.
- **ChatbotDefinitionForm**: localized field groups, source-scope explanation,
  invalid, dirty, submitting, saved, and version-conflict states. Conflict offers
  reload-current before another write.
- **TestChatSurface**: session loading/empty, ready, streaming, cancelling,
  detached/reattaching, completed, partial-error, disabled-chatbot, citations,
  and feedback-stored states. Token-level updates are not announced through a live
  region.

### Interaction, accessibility, and accepted debt

- Interaction mechanics adapt beui.dev `button` state replacement and
  `center-morph-modal` overlay hierarchy to the existing motion tokens. The
  implementation uses CSS/Radix primitives rather than adding a motion runtime;
  reduced motion removes transforms and keeps short opacity feedback.
- Workspace changes, sign-out, revocation, and archive clear dependent UI only
  after the BFF response establishes the new authority state. Cancel and reattach
  remain interruptible, and route changes abort in-flight UI requests.
- Every form error is associated with its field; dialogs restore focus; icon-only
  buttons have accessible names; keyboard focus uses `--rs-focus`; mobile targets
  are at least 44px. EN and RU copy share the same hierarchy and may wrap naturally
  without truncating actions.
- Accepted Task 10 debt: the local invitation inbox remains an external Mailpit
  surface linked from the development UI; production email-provider UX is outside
  FR-013. Widget/public-key controls and billing remain outside this stage.

## Group 1 unified RAG-Studio shell contract (FR-021)

This section is the implementation contract for Group 1. It supersedes the
separate user-facing SaaS shell without claiming that the current checkout has
already performed that cutover. The governing route inventory and migration
table live in `docs/features/unified-rag-studio-shell-auth.md`.

### Public access boundary — approved 2026-08-20

Authentication is a **public access surface**, not a reduced authenticated
application. Before the BFF has confirmed a session, `/`, `/sign-in`, and
`/sign-up` use a minimal `PublicAuthShell` with product identity, locale, a
short factual product description, and the sign-in/sign-up form. The public
surface must not render the application top navigation, connection status,
page eyebrow/title, workspace switcher, account role, user menu, drawer, or
any disabled-looking product destination. In particular, it must never show
Home, Settings, or Chat as public or blocked routes: those labels imply access
to product functionality the visitor cannot yet use.

On wide public-auth viewports, the factual product label and description form a
quiet left hero beside the credential panel. The panel is deliberately offset
slightly to the right of the center line, creating a purposeful reading order
without introducing a second navigation system or marketing claims. At tablet
and mobile widths, the hero stacks above the form and the form remains the sole
primary task.

`/app` and all of its descendants are authenticated application routes. Only
after a confirmed session may one `AppShell` render its product navigation,
status, context controls, and page heading. An unauthenticated protected-route
request is held as an in-memory, allow-listed internal return path; it contains
no query, bearer, role, Account, or Workspace value, cannot point off-origin,
and is cleared after the first successful recovery. The fallback target is
`/app`.

The public surface may include one quiet secondary `About RAG-Studio` text
link when truthful content exists, but it is not an application tab or a
second navigation system. A longer marketing/conversion journey, claims,
pricing, and decorative effects remain owned by FR-018; Group 1 does not
invent them. Public auth is task-first: one primary action, visible field
labels, keyboard focus, sanitized recovery/confirmation errors, and no
access-token or session detail in the DOM.

### Canonical product and navigation — FR021-DESIGN-CANONICAL

- `/app` is the one canonical authenticated RAG-Studio application. `/` is the
  public access entry: it recovers a session and then renders either the
  minimal public authentication state or `/app`; it never presents a competing
  product brand or shell.
- Exactly one `AppShell` owns the product identity, primary top navigation,
  locale control, user menu, page heading, and mobile drawer. The desktop header
  is one line: identity at the left, primary navigation centered, locale and an
  icon-only profile control at the right. Workspace selection is not a persistent
  header card; it is a labelled task surface on Home and remains available in the
  mobile drawer.
  The selected local navigation item is the sole location cue for Chat and
  Settings: the shell does not repeat a `RAG-Studio` eyebrow or the active
  tab's title above either surface. Feature content retains only meaningful
  task copy and accessible region names. Home retains its welcome heading.
  A former `/saas` route may only redirect or render its canonical destination;
  it must never mount `SaasShell` beside or inside `AppShell`.
- Navigation lists only destinations backed by the current Group 1 surface:
  Home/Personal Lab entry, Chat, Settings, and the active Workspace’s available
  Chatbots, Sources, and People destinations. Account context is a control, not
  a second navigation bar. Knowledge, Agents, Widget Bots, Usage, and Billing
  are omitted until their owning FR supplies a functional route and contract.
- The active item has a text label, `aria-current`, and a non-colour cue. A
  disabled-looking or “coming soon” item is not a substitute for a destination
  and must not be rendered in the canonical shell.

### Trusted context and role-honest states — FR021-DESIGN-ROLE-STATES

- The labelled Home context surface identifies the server-confirmed Account and
  exactly `Personal Lab` or the active Workspace, followed by a textual effective
  role badge (`Owner`, `Admin`, or `Member`) where a Workspace is selected. The
  same full selector is available in the mobile drawer. A Personal Lab does not
  invent a Workspace role.
- Context data is loading until the BFF confirms it. The old context’s child
  content is cleared before the new context’s dependent content can render.
  Browser-held IDs, cached roles, and hidden navigation state are presentation
  hints only and never authority.
- Owner actions are limited to real ownership and membership lifecycle tasks;
  admin actions are limited to real invitations, sources, and chatbot
  management; member views retain chatbot/test access but show a plain,
  localized permission explanation for unavailable mutation work. Do not render
  a dead action, a fake control, or a raw policy/API detail.
- Required public-access outcomes are: initial/loading; unauthenticated sign-in
  or sign-up; confirmation-required; and a sanitized recoverable auth error.
  Required authenticated shell outcomes are: no-context/empty; selection-pending;
  recoverable service error; forbidden; revoked/archived/unavailable selection;
  and signed-out. Forbidden, revoked, and archived outcomes clear stale
  workspace and agent content, retain only safe account/context-recovery UI,
  and offer a real available-context selection or sign-in action.
- The account/user menu contains only real session controls: labelled user
  identity, sign out, and locale. It must not expose provider tokens, account
  secrets, raw error text, or unimplemented profile/billing controls.

### Responsive and localized composition — FR021-DESIGN-VIEWPORT-MATRIX

| Viewport | EN and RU contract | Observable layout rule |
| --- | --- | --- |
| 360 px | Compact header; labelled menu and context controls are at least 44 px; one-column content and wrapped action groups | Drawer is the only off-canvas navigation, controls retain visible labels, and no primary surface horizontally scrolls |
| 768 px | Header remains compact when the full top bar would collide; contextual content stacks before labels or role badges compress | Drawer focus is trapped while open and returns to its trigger on close; long Russian Account/Workspace names wrap without clipping actions |
| 1440 px | One persistent top bar and bounded page body; context is reachable from Home | No duplicate rail, no second product nav, and reading/content widths follow the existing layout tokens |

All EN/RU strings use the shared locale system; neither language may depend on
fixed-width truncation for Account, Personal Lab, Workspace, or role labels.
Keyboard focus uses `--rs-focus`, icon-only controls have accessible names, and
all state changes honour reduced motion. The design remains dark-first and uses
the existing semantic tokens, surface hierarchy, restrained gold emphasis, and
blue-violet interactive state rather than a new SaaS brand.

## Stage boundaries and visual QA

- **Stage 2 / FR-012:** build the React visual system and replace existing Welcome, Settings, and Chat behavior with parity. The Dashboard location needs its own concrete data and acceptance criteria before it becomes a working route; the reference dashboard does not authorize invented quality metrics.
- **Stage 3:** workspace context, chatbot configuration, widget settings, billing, and conversion surfaces follow FR-013 through FR-018.
- Old visual identity is deleted only after the React cutover is verified, preserving a safe rollback path in the meantime.

Every UI task follows:

`design-system-style-intelligence -> frontend-design-director -> react-shadcn-ui-contract -> omo:visual-qa -> in-app Browser confirmation`

Verification records the governing reference, route, scenario, viewport, observed state, keyboard/focus behavior, reduced-motion behavior, and screenshots. A visual match without working data, error states, accessible interaction, or mobile behavior is not accepted.

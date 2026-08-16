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

## Stage boundaries and visual QA

- **Stage 2 / FR-012:** build the React visual system and replace existing Welcome, Settings, and Chat behavior with parity. The Dashboard location needs its own concrete data and acceptance criteria before it becomes a working route; the reference dashboard does not authorize invented quality metrics.
- **Stage 3:** workspace context, chatbot configuration, widget settings, billing, and conversion surfaces follow FR-013 through FR-018.
- Old visual identity is deleted only after the React cutover is verified, preserving a safe rollback path in the meantime.

Every UI task follows:

`design-system-style-intelligence -> frontend-design-director -> react-shadcn-ui-contract -> omo:visual-qa -> in-app Browser confirmation`

Verification records the governing reference, route, scenario, viewport, observed state, keyboard/focus behavior, reduced-motion behavior, and screenshots. A visual match without working data, error states, accessible interaction, or mobile behavior is not accepted.

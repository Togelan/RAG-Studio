---
name: react-shadcn-ui-contract
description: Build or review the approved React, TypeScript, Tailwind CSS, and shadcn/ui SaaS frontend for RAG-Studio. Use after a design direction is established for components, tokens, accessibility, responsive states, icons, and production UI consistency.
---

# React/shadcn Production UI Contract

## Prerequisites

Read `DESIGN.md` and the relevant feature design before implementation. Use
`frontend-design-director` for visual decisions and
`design-system-style-intelligence` when references need extraction. Do not
introduce a competing component library.

## Implementation contract

- Use React with TypeScript, Tailwind CSS, and only the shadcn/ui primitives
  needed by the feature.
- Define semantic design tokens for color, typography, spacing, radius,
  elevation, and motion. Do not scatter arbitrary values through components.
- Build reusable product primitives before duplicating markup.
- Use the project icon library; use Lucide when no project choice exists. Do
  not draw ad-hoc SVGs or use emoji as functional icons.
- Use semantic HTML, labelled fields, native buttons, visible focus states,
  WCAG AA contrast, keyboard navigation, and accessible names for icon-only
  controls.
- Design desktop and mobile states deliberately. Provide loading, empty,
  disabled, validation, and error states for interactive flows.
- Prefer CSS transitions. Add an animation runtime only for a demonstrated
  interaction need and always support reduced motion.

## Verification

Run the project UI checks plus `omo:visual-qa` against real browser viewports.
Verify no horizontal overflow, 44px minimum touch targets where applicable,
and that public/widget surfaces never expose privileged data or secrets.

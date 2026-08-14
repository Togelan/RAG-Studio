---
name: design-system-style-intelligence
description: Extract an evidence-based RAG-Studio design system from user-provided UI references before a new page or substantial UI redesign. Use to select and record tokens, layout grammar, component anatomy, states, responsive behavior, and visual constraints in DESIGN.md.
---

# Design-System Style Intelligence

## Inputs and boundary

Use only the approved product direction and visual references supplied by the
user or present in the current checkout. Treat references as source material,
not material to copy. Do not start UI implementation until the references have
been inspected.

## Workflow

1. Record the selected references and the product reason each one fits.
2. Extract their reusable visual grammar: semantic colors, type roles, spacing,
   grids, surfaces, radii, borders, elevation, motion, responsive behavior,
   component anatomy, and interaction states.
3. Synthesize an original RAG-Studio `DESIGN.md` containing tokens, component
   rules, accessibility constraints, mobile behavior, and accepted design debt.
4. Resolve conflicts in favor of usability, accessibility, performance, and
   the approved calm knowledge-workspace direction.

## Guardrails

- Do not copy logos, brand names, proprietary artwork, or exact marketing
  copy from references.
- Do not introduce a visual decision merely because it is fashionable.
- Keep the widget independently themeable; customer branding must change
  semantic tokens, not internal component structure.
- Update `DESIGN.md` before a new token, primitive, state, or motion rule is
  used in implementation.

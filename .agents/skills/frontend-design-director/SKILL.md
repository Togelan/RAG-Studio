---
name: frontend-design-director
description: Establish a distinctive, accessible visual direction before designing or substantially redesigning any RAG-Studio SaaS page, dashboard, marketing page, or product flow. Use before React UI implementation; do not use for backend-only changes or isolated copy edits.
---

# Frontend Design Director

## Purpose

Act as the design lead for the approved SaaS migration. Turn the product brief
and supplied visual references into an intentional interface, not a generic AI
template.

## Before implementation

1. Read the relevant feature design, current `DESIGN.md` when it exists, and
   every reference supplied by the user.
2. Establish the page's primary user job, audience, visual thesis, content
   hierarchy, responsive composition, and one purposeful signature moment.
3. Create or update `DESIGN.md` before changing UI code. Delegate reference
   extraction to `design-system-style-intelligence` and implementation rules to
   `react-shadcn-ui-contract`.

## Design direction

- Use the approved calm, premium knowledge-workspace direction unless the
  feature design or user references supersede it.
- Make typography, surfaces, spacing, and hierarchy specific to the product.
- Prefer meaningful composition over symmetric card grids.
- Use one restrained accent and purposeful motion; respect
  `prefers-reduced-motion`.
- Do not default to centered hero + gradient + three cards, uniform large
  radii, decorative labels, random glows, or placeholder copy.

## Quality gate

Before handoff, verify that the main task is obvious, mobile preserves the
hierarchy, keyboard focus is visible, and loading, empty, error, and disabled
states have been designed where applicable. Require browser-based visual QA;
do not approve based on source code alone.

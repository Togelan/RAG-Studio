---
name: ui-design
description: Teaches @dev how to build a beautiful, consistent web interface for RAG-Studio. Covers color palette, spacing, typography, button styles, and layout patterns. Must view reference images before writing any HTML/CSS.
---

# UI Design Skill

## When to Use

Invoke this skill **before writing any HTML/CSS** for RAG-Studio's web interface:
- Creating new pages or templates in `src/api/templates/`
- Styling Jinja2 templates
- Adding buttons, forms, navigation, or layout components
- Reviewing or refactoring existing UI

---

## Rule Zero: Reference First

> **Before writing any HTML/CSS, view the reference images in `references/` and mimic the look.**

Open each image in `references/` and study:
- The overall layout and spacing.
- The color combinations and contrast ratios.
- How buttons, inputs, and cards are styled.
- The typography hierarchy (headings, body, captions).
- How interactive states (hover, focus, active) are handled.

**Do not invent.** Translate what you see into clean, semantic HTML and modern CSS.

---

## Design System

### Color Palette

| Token | Hex | Usage |
|-------|-----|-------|
| `--color-bg-primary` | `#0F1117` | Main background |
| `--color-bg-secondary` | `#1A1D27` | Card, sidebar, modal backgrounds |
| `--color-bg-tertiary` | `#252830` | Input fields, code blocks, hover states |
| `--color-border` | `#2E3039` | Borders, dividers |
| `--color-text-primary` | `#E8EAED` | Headings, body text |
| `--color-text-secondary` | `#9AA0A6` | Placeholders, captions, muted text |
| `--color-accent` | `#6C5CE7` | Primary buttons, links, active states |
| `--color-accent-hover` | `#7D6EF0` | Button hover, focus rings |
| `--color-success` | `#00C853` | Success badges, checkmarks |
| `--color-warning` | `#FFAB00` | Warning badges, alerts |
| `--color-error` | `#FF5252` | Error text, destructive buttons |
| `--color-info` | `#448AFF` | Info badges, links |

### Spacing Scale

Use a 4px base unit. All spacing must be multiples of 4.

| Token | Value | Usage |
|-------|-------|-------|
| `--space-xs` | `4px` | Icon padding, tight gaps |
| `--space-sm` | `8px` | Inline gaps, label spacing |
| `--space-md` | `16px` | Card padding, section gaps |
| `--space-lg` | `24px` | Section margins, container padding |
| `--space-xl` | `32px` | Page margins, large separators |
| `--space-2xl` | `48px` | Hero spacing, major sections |
| `--space-3xl` | `64px` | Page top/bottom padding |

### Typography

| Token | Font Size | Line Height | Font Weight | Usage |
|-------|-----------|-------------|-------------|-------|
| `--text-xs` | `12px` | `1.5` | `400` | Captions, badges, metadata |
| `--text-sm` | `14px` | `1.5` | `400` | Secondary text, labels |
| `--text-base` | `16px` | `1.6` | `400` | Body text, inputs, buttons |
| `--text-lg` | `18px` | `1.5` | `500` | Card titles, emphasized text |
| `--text-xl` | `24px` | `1.4` | `600` | Section headings |
| `--text-2xl` | `32px` | `1.3` | `700` | Page titles |
| `--text-3xl` | `40px` | `1.2` | `800` | Hero headings |

- **Font family**: `'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`
- **Monospace font**: `'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace`

### Button Styles

#### Primary Button
```css
.btn-primary {
  background: var(--color-accent);
  color: #fff;
  padding: var(--space-sm) var(--space-lg);
  border: none;
  border-radius: 8px;
  font-size: var(--text-base);
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s ease, transform 0.1s ease;
}
.btn-primary:hover {
  background: var(--color-accent-hover);
}
.btn-primary:active {
  transform: scale(0.98);
}
.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
```

#### Secondary Button
```css
.btn-secondary {
  background: transparent;
  color: var(--color-text-primary);
  padding: var(--space-sm) var(--space-lg);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  font-size: var(--text-base);
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s ease, border-color 0.2s ease;
}
.btn-secondary:hover {
  background: var(--color-bg-tertiary);
  border-color: var(--color-text-secondary);
}
```

#### Destructive Button
```css
.btn-destructive {
  background: var(--color-error);
  color: #fff;
  padding: var(--space-sm) var(--space-lg);
  border: none;
  border-radius: 8px;
  font-size: var(--text-base);
  font-weight: 500;
  cursor: pointer;
}
```

### Input Fields
```css
.input-field {
  background: var(--color-bg-tertiary);
  color: var(--color-text-primary);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: var(--space-sm) var(--space-md);
  font-size: var(--text-base);
  font-family: inherit;
  width: 100%;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
.input-field:focus {
  outline: none;
  border-color: var(--color-accent);
  box-shadow: 0 0 0 3px rgba(108, 92, 231, 0.25);
}
.input-field::placeholder {
  color: var(--color-text-secondary);
}
```

### Card Pattern
```css
.card {
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  border-radius: 12px;
  padding: var(--space-lg);
}
.card-header {
  font-size: var(--text-lg);
  font-weight: 500;
  margin-bottom: var(--space-md);
}
.card-body {
  color: var(--color-text-secondary);
  line-height: 1.6;
}
```

---

## Layout Principles

1. **Single-column centered layout** — max-width 960px, centered with `margin: 0 auto`.
2. **Vertical rhythm** — sections separated by `var(--space-xl)` or `var(--space-2xl)`.
3. **Consistent corner radius** — `8px` for inputs/buttons, `12px` for cards/modals, `16px` for main containers.
4. **Depth with borders, not shadows** — use `1px solid var(--color-border)` for separation. Only use shadows for modals and dropdowns.
5. **Hover transitions** — all interactive elements must have a `0.2s ease` transition on color/background/border changes.
6. **Focus rings** — all focusable elements must show `box-shadow: 0 0 0 3px rgba(108, 92, 231, 0.25)` on `:focus-visible`.

---

## Accessibility Rules

- All form inputs must have associated `<label>` elements.
- Color contrast must meet WCAG AA (4.5:1 for normal text, 3:1 for large text).
- Buttons must have visible focus indicators.
- Use semantic HTML: `<nav>`, `<main>`, `<section>`, `<header>`, `<footer>`.
- Add `aria-label` to icon-only buttons.
- Ensure all interactive elements are keyboard accessible.

---

## Template Structure

All Jinja2 templates must extend a base layout:

```html
<!-- templates/base.html -->
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{% block title %}RAG-Studio{% endblock %}</title>
  <link rel="stylesheet" href="/static/css/main.css">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
</head>
<body class="bg-primary text-primary">
  <nav class="navbar">{% block navbar %}{% endblock %}</nav>
  <main class="container">{% block content %}{% endblock %}</main>
  <footer class="footer">{% block footer %}{% endblock %}</footer>
</body>
</html>
```

---

## Checklist Before Submitting UI

- [ ] Viewed all reference images in `references/` and matched the look.
- [ ] Used only colors from the palette above (no ad-hoc hex values).
- [ ] Spacing uses multiples of 4px (`--space-*` tokens).
- [ ] All interactive elements have hover and focus states.
- [ ] Semantic HTML used throughout.
- [ ] Form inputs have labels.
- [ ] Template extends `base.html`.
- [ ] CSS is in `static/css/`, not inline or in `<style>` blocks.

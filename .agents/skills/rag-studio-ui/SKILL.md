---
name: rag-studio-ui
description: Change or review RAG-Studio FastAPI pages, Jinja templates, browser JavaScript, CSS, or English/Russian locale files. Use for work under src/api/templates, src/api/static, or src/api/locales.
---

# RAG-Studio UI workflow

Inspect the existing template, CSS, JavaScript, and related route before making a change. Preserve the project’s current visual language instead of importing a UI framework or inventing a separate design system.

- Templates live in `src/api/templates/`.
- CSS lives in `src/api/static/css/`; browser JavaScript lives in `src/api/static/js/`.
- Keep UI text localizable. Whenever a key is added or changed, make the same structural change in both `en.json` and `ru.json`.
- Keep forms labeled, keyboard focus visible, and interactive controls usable at narrow widths.
- Exercise the matching UI/API tests. If the app can be run, verify the touched page at desktop and mobile widths; otherwise say that visual verification was not performed.

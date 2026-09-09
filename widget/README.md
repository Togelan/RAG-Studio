# RAG-Studio widget foundation

The package emits one self-registering, versioned browser artifact:
`dist/rag-studio-widget.v1.js`. Embed it with one public widget identifier:

```html
<script src="/path/rag-studio-widget.v1.js" defer></script>
<rag-studio-widget widget-key="public_widget_identifier"></rag-studio-widget>
```

`widget-key` is a public identifier, never a credential. This foundation does
not import the React application, private API clients, user state, or secrets.
When the API is hosted separately from the script, set `api-base-url` to its
HTTPS origin. The widget calls only the public proof, stream, and cancel routes;
it never sends cookies or stores the conversation.

## Semantic theme tokens

Set only these documented custom properties on `rag-studio-widget`:

- `--rsw-accent`: primary interactive color.
- `--rsw-accent-ink`: text on the accent color.
- `--rsw-surface`: panel surface.
- `--rsw-surface-raised`: grouped/raised surface.
- `--rsw-text`: primary text.
- `--rsw-text-muted`: supporting text.
- `--rsw-border`: border and divider color.
- `--rsw-focus`: visible keyboard focus ring.
- `--rsw-radius`: panel radius.
- `--rsw-font`: UI font stack.

All layout, focus, overlay, and motion rules remain internal to the Shadow DOM.
The fixed `approved.html`, `hostile.html`, and `rejected.html` fixtures exercise
normal embedding, aggressive host CSS, and a missing-script failure.

## Reproducible verification

Use Node 24.19.0 and npm 11.17.0, then run `npm ci` and `npm run verify`.

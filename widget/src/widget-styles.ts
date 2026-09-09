export const widgetStyles = `
  :host {
    all: initial;
    --rsw-accent: #9390ff;
    --rsw-accent-ink: #080c14;
    --rsw-surface: #0e1522;
    --rsw-surface-raised: #19263a;
    --rsw-text: #f5f7fb;
    --rsw-text-muted: #a6b2c4;
    --rsw-border: #43546e;
    --rsw-focus: #b4b2ff;
    --rsw-radius: 12px;
    --rsw-font: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    --rsw-space-1: 4px;
    --rsw-space-2: 8px;
    --rsw-space-3: 12px;
    --rsw-space-4: 16px;
    --rsw-space-5: 20px;
    --rsw-space-6: 24px;
    --rsw-target: 44px;
    --rsw-motion-press: 80ms;
    --rsw-motion-overlay: 180ms;
    position: fixed;
    z-index: 2147483000;
    right: var(--rsw-space-6);
    bottom: var(--rsw-space-6);
    display: block;
    color: var(--rsw-text);
    color-scheme: dark;
    contain: style;
    font-family: var(--rsw-font);
    font-size: 16px;
    font-style: normal;
    font-weight: 400;
    line-height: 1.5;
    text-align: left;
  }

  *,
  *::before,
  *::after {
    box-sizing: border-box;
  }

  button,
  textarea {
    margin: 0;
    border: 0;
    font: inherit;
    letter-spacing: normal;
    text-transform: none;
  }

  button {
    min-height: var(--rsw-target);
    cursor: pointer;
  }

  button:focus-visible,
  textarea:focus-visible {
    outline: 3px solid var(--rsw-focus);
    outline-offset: 2px;
  }

  button:disabled {
    cursor: not-allowed;
    opacity: 0.58;
  }

  .rsw-root {
    display: grid;
    justify-items: end;
  }

  .rsw-launcher {
    min-width: 164px;
    border: 1px solid color-mix(in srgb, var(--rsw-accent) 68%, var(--rsw-border));
    border-radius: 999px;
    background: var(--rsw-accent);
    color: var(--rsw-accent-ink);
    padding: var(--rsw-space-3) var(--rsw-space-5);
    box-shadow: 0 12px 32px color-mix(in srgb, var(--rsw-surface) 48%, transparent);
    font-weight: 700;
    transition:
      transform var(--rsw-motion-press) ease-out,
      filter var(--rsw-motion-press) ease-out;
  }

  .rsw-launcher:hover {
    filter: brightness(1.06);
  }

  .rsw-launcher:active {
    transform: scale(0.98);
  }

  .rsw-panel {
    position: fixed;
    right: var(--rsw-space-6);
    bottom: calc(var(--rsw-target) + var(--rsw-space-6) + var(--rsw-space-3));
    display: grid;
    width: min(360px, calc(100vw - 32px));
    max-height: min(620px, calc(100dvh - 120px));
    grid-template-rows: auto minmax(0, 1fr) auto;
    overflow: hidden;
    border: 1px solid var(--rsw-border);
    border-radius: var(--rsw-radius);
    background: var(--rsw-surface);
    box-shadow: 0 24px 72px color-mix(in srgb, #080c14 58%, transparent);
    animation: rsw-open var(--rsw-motion-overlay) ease-out;
  }

  .rsw-panel[hidden],
  .rsw-launcher[hidden] {
    display: none;
  }

  @keyframes rsw-open {
    from {
      opacity: 0;
      transform: translateY(8px);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }

  .rsw-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: var(--rsw-space-4);
    border-bottom: 1px solid var(--rsw-border);
    padding: var(--rsw-space-4);
  }

  .rsw-header h2,
  .rsw-header p,
  .rsw-content p,
  .rsw-composer p {
    margin: 0;
  }

  .rsw-header h2 {
    color: var(--rsw-text);
    font-size: 18px;
    line-height: 1.3;
  }

  .rsw-eyebrow {
    color: var(--rsw-accent);
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  .rsw-close {
    min-width: var(--rsw-target);
    border-radius: 8px;
    background: transparent;
    color: var(--rsw-text-muted);
    padding: var(--rsw-space-2);
  }

  .rsw-close:hover {
    background: var(--rsw-surface-raised);
    color: var(--rsw-text);
  }

  .rsw-content {
    min-height: 180px;
    overflow-y: auto;
    padding: var(--rsw-space-4);
    scrollbar-color: var(--rsw-border) var(--rsw-surface);
  }

  .rsw-content > p {
    max-width: 42ch;
    color: var(--rsw-text-muted);
    font-size: 14px;
  }

  .rsw-welcome {
    display: grid;
    gap: var(--rsw-space-1);
    margin-top: var(--rsw-space-4);
    border: 1px solid var(--rsw-border);
    border-radius: 10px;
    background: var(--rsw-surface-raised);
    padding: var(--rsw-space-4);
  }

  .rsw-welcome span {
    color: var(--rsw-text-muted);
    font-size: 13px;
  }

  .rsw-answer {
    margin-top: var(--rsw-space-4);
    color: var(--rsw-text);
    overflow-wrap: anywhere;
    white-space: pre-wrap;
  }

  .rsw-citations {
    display: flex;
    flex-wrap: wrap;
    gap: var(--rsw-space-2);
    margin: var(--rsw-space-3) 0 0;
    padding: 0;
    list-style: none;
  }

  .rsw-citations li {
    border: 1px solid var(--rsw-border);
    border-radius: 999px;
    background: var(--rsw-surface-raised);
    color: var(--rsw-text-muted);
    padding: var(--rsw-space-1) var(--rsw-space-2);
    font-size: 12px;
  }

  .rsw-status {
    margin-top: var(--rsw-space-3) !important;
    color: var(--rsw-text-muted);
    font-size: 13px;
  }

  .rsw-retry {
    margin-top: var(--rsw-space-2);
    border: 1px solid var(--rsw-border);
    border-radius: 8px;
    background: var(--rsw-surface-raised);
    color: var(--rsw-text);
    padding: var(--rsw-space-2) var(--rsw-space-3);
  }

  .rsw-retry[hidden] {
    display: none;
  }

  .rsw-composer {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: var(--rsw-space-2);
    border-top: 1px solid var(--rsw-border);
    padding: var(--rsw-space-4);
  }

  .rsw-composer label,
  .rsw-composer p {
    grid-column: 1 / -1;
  }

  .rsw-composer label {
    color: var(--rsw-text);
    font-size: 13px;
    font-weight: 650;
  }

  .rsw-composer textarea {
    min-width: 0;
    min-height: var(--rsw-target);
    resize: vertical;
    border: 1px solid var(--rsw-border);
    border-radius: 8px;
    background: var(--rsw-surface-raised);
    color: var(--rsw-text);
    padding: var(--rsw-space-2) var(--rsw-space-3);
  }

  .rsw-composer textarea::placeholder {
    color: var(--rsw-text-muted);
  }

  .rsw-composer button {
    align-self: end;
    border-radius: 8px;
    background: var(--rsw-accent);
    color: var(--rsw-accent-ink);
    padding: var(--rsw-space-2) var(--rsw-space-4);
    font-weight: 700;
  }

  .rsw-composer p {
    color: var(--rsw-text-muted);
    font-size: 12px;
  }

  @media (max-width: 400px) {
    :host {
      right: var(--rsw-space-3);
      bottom: max(var(--rsw-space-3), env(safe-area-inset-bottom));
      left: var(--rsw-space-3);
    }

    .rsw-root,
    .rsw-launcher {
      width: 100%;
    }

    .rsw-panel {
      right: var(--rsw-space-3);
      bottom: calc(var(--rsw-target) + var(--rsw-space-5) + env(safe-area-inset-bottom));
      left: var(--rsw-space-3);
      width: auto;
      max-height: calc(100dvh - 88px - env(safe-area-inset-bottom));
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .rsw-panel {
      animation: none;
    }

    .rsw-launcher {
      transition-duration: 1ms;
    }
  }
`

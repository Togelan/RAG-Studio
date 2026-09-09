export const widgetTemplate = `
  <style data-rsw-styles></style>
  <div class="rsw-root">
    <section
      class="rsw-panel"
      role="dialog"
      aria-modal="true"
      aria-labelledby="rsw-title"
      aria-describedby="rsw-description"
      hidden
    >
      <header class="rsw-header">
        <div>
          <p class="rsw-eyebrow">RAG-Studio</p>
          <h2 id="rsw-title">Ask the knowledge base</h2>
        </div>
        <button class="rsw-close" type="button" aria-label="Close support chat">Close</button>
      </header>
      <div class="rsw-content">
        <p id="rsw-description">
          Ask about the knowledge shared for this site. Answers will include sources when available.
        </p>
        <div class="rsw-welcome" role="status">
          <strong>Ask a question to get started.</strong>
          <span>This embedded conversation is not saved.</span>
        </div>
        <div class="rsw-answer" aria-label="Answer"></div>
        <ul class="rsw-citations" aria-label="Sources"></ul>
        <p class="rsw-status" role="status" aria-live="polite">Connecting securely…</p>
        <button class="rsw-retry" type="button" hidden>Try again</button>
      </div>
      <form class="rsw-composer">
        <label for="rsw-question">Your question</label>
        <textarea
          id="rsw-question"
          name="question"
          rows="2"
          placeholder="Type a question"
          autocomplete="off"
        ></textarea>
        <button class="rsw-send" type="submit" disabled aria-describedby="rsw-foundation-note">Send</button>
        <p id="rsw-foundation-note">Answers use only knowledge published for this site.</p>
      </form>
    </section>
    <button
      class="rsw-launcher"
      type="button"
      aria-label="Open support chat"
      aria-expanded="false"
    >
      Ask RAG-Studio
    </button>
  </div>
`

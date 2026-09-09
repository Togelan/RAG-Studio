import {
  bootstrapPublicWidget,
  cancelPublicWidget,
  type PublicCitation,
  type PublicProof,
  type PublicStreamEvent,
  PublicTransportError,
  streamPublicWidget,
} from "./public-transport"
import { widgetStyles } from "./widget-styles"
import { widgetTemplate } from "./widget-template"

export const WIDGET_ELEMENT_NAME = "rag-studio-widget"

function requireButton(root: ShadowRoot, selector: string): HTMLButtonElement {
  const element = root.querySelector<HTMLButtonElement>(selector)
  if (element === null) throw new TypeError(`Widget template is missing ${selector}`)
  return element
}

function requireElement(root: ShadowRoot, selector: string): HTMLElement {
  const element = root.querySelector<HTMLElement>(selector)
  if (element === null) throw new TypeError(`Widget template is missing ${selector}`)
  return element
}

function requireInput(root: ShadowRoot, selector: string): HTMLTextAreaElement {
  const element = root.querySelector<HTMLTextAreaElement>(selector)
  if (element === null) throw new TypeError(`Widget template is missing ${selector}`)
  return element
}

function requireForm(root: ShadowRoot, selector: string): HTMLFormElement {
  const element = root.querySelector<HTMLFormElement>(selector)
  if (element === null) throw new TypeError(`Widget template is missing ${selector}`)
  return element
}

export class WidgetElement extends HTMLElement {
  static get observedAttributes(): string[] {
    return ["api-base-url", "open", "widget-key"]
  }

  readonly #launcher: HTMLButtonElement
  readonly #close: HTMLButtonElement
  readonly #dialog: HTMLElement
  readonly #input: HTMLTextAreaElement
  readonly #form: HTMLFormElement
  readonly #send: HTMLButtonElement
  readonly #retry: HTMLButtonElement
  readonly #status: HTMLElement
  readonly #answer: HTMLElement
  readonly #citations: HTMLElement
  #proof: PublicProof | null = null
  #streaming = false
  #connected = false

  constructor() {
    super()
    const shadow = this.attachShadow({ mode: "open", delegatesFocus: true })
    shadow.innerHTML = widgetTemplate

    const style = shadow.querySelector<HTMLStyleElement>("[data-rsw-styles]")
    if (style === null) throw new TypeError("Widget template is incomplete")

    style.textContent = widgetStyles
    this.#launcher = requireButton(shadow, ".rsw-launcher")
    this.#close = requireButton(shadow, ".rsw-close")
    this.#send = requireButton(shadow, ".rsw-send")
    this.#retry = requireButton(shadow, ".rsw-retry")
    this.#dialog = requireElement(shadow, ".rsw-panel")
    this.#status = requireElement(shadow, ".rsw-status")
    this.#answer = requireElement(shadow, ".rsw-answer")
    this.#citations = requireElement(shadow, ".rsw-citations")
    this.#input = requireInput(shadow, "#rsw-question")
    this.#form = requireForm(shadow, ".rsw-composer")

    this.#launcher.addEventListener("click", this.#open)
    this.#close.addEventListener("click", this.#closeWidget)
    this.#retry.addEventListener("click", this.#retryBootstrap)
    this.#form.addEventListener("submit", this.#submit)
    shadow.addEventListener("keydown", this.#handleKeydown)
  }

  connectedCallback(): void {
    this.#connected = true
    this.#syncOpenState()
    void this.#bootstrap()
  }

  disconnectedCallback(): void {
    this.#connected = false
    void this.#cancelActive()
  }

  attributeChangedCallback(name: string): void {
    this.#syncOpenState()
    if (this.#connected && name !== "open") void this.#bootstrap()
  }

  readonly #open = (): void => {
    this.setAttribute("open", "")
  }

  readonly #closeWidget = (): void => {
    this.removeAttribute("open")
    void this.#cancelActive()
  }

  readonly #submit = (event: SubmitEvent): void => {
    event.preventDefault()
    const message = this.#input.value.trim()
    if (message.length === 0 || message.length > 4000 || this.#streaming) return
    void this.#sendMessage(message)
  }

  readonly #retryBootstrap = (): void => {
    void this.#bootstrap()
  }

  readonly #handleKeydown = (event: Event): void => {
    if (!(event instanceof KeyboardEvent)) return
    if (!this.hasAttribute("open")) return
    if (event.key === "Escape") {
      event.preventDefault()
      this.#closeWidget()
      return
    }
    if (event.key !== "Tab") return
    const focusable = [this.#close, this.#input, this.#send, this.#retry].filter(
      (element) => !(element instanceof HTMLButtonElement && (element.disabled || element.hidden)),
    )
    const activeElement = this.shadowRoot?.activeElement
    const current = focusable.findIndex((element) => element === activeElement)
    if (current < 0) return
    const direction = event.shiftKey ? -1 : 1
    const next = (current + direction + focusable.length) % focusable.length
    const target = focusable[next]
    if (target === undefined) return
    event.preventDefault()
    target.focus()
  }

  #syncOpenState(): void {
    const isOpen = this.hasAttribute("open")
    this.#dialog.hidden = !isOpen
    this.#launcher.hidden = isOpen
    this.#launcher.setAttribute("aria-expanded", String(isOpen))
    if (!this.isConnected) return
    if (isOpen) this.#close.focus()
    else this.#launcher.focus()
  }

  get #publicKey(): string | null {
    const value = this.getAttribute("widget-key")?.trim()
    return value === undefined || value.length === 0 ? null : value
  }

  get #baseUrl(): string {
    return this.getAttribute("api-base-url")?.trim() || globalThis.location.origin
  }

  async #bootstrap(): Promise<PublicProof | null> {
    const publicKey = this.#publicKey
    this.#proof = null
    this.#setReady(false)
    this.#setStatus("Connecting securely…")
    if (publicKey === null) {
      this.#setStatus("Chat is currently unavailable.", true)
      return null
    }
    try {
      const proof = await bootstrapPublicWidget(this.#baseUrl, publicKey)
      if (!this.#connected || publicKey !== this.#publicKey) return null
      this.#proof = proof
      this.#setReady(true)
      this.#setStatus("Ready for your question.")
      return proof
    } catch (error) {
      this.#showFailure(
        error instanceof PublicTransportError ? error : new PublicTransportError("protocol"),
        true,
      )
      return null
    }
  }

  async #sendMessage(message: string): Promise<void> {
    const publicKey = this.#publicKey
    if (publicKey === null) return
    this.#streaming = true
    this.#setReady(false)
    this.#resetResponse()
    this.#setStatus("Preparing your answer…")
    const proof = await this.#bootstrap()
    if (proof === null) {
      this.#streaming = false
      return
    }
    try {
      await this.#runStream(publicKey, proof, message, true)
    } catch (error) {
      this.#showFailure(
        error instanceof PublicTransportError ? error : new PublicTransportError("protocol"),
        true,
      )
    } finally {
      this.#streaming = false
      if (this.#proof !== null) this.#setReady(true)
    }
  }

  async #runStream(
    publicKey: string,
    proof: PublicProof,
    message: string,
    allowRefresh: boolean,
  ): Promise<void> {
    try {
      await streamPublicWidget(this.#baseUrl, publicKey, proof, message, this.#onEvent)
    } catch (error) {
      if (
        allowRefresh &&
        error instanceof PublicTransportError &&
        error.kind === "http" &&
        error.status === 401
      ) {
        const refreshed = await this.#bootstrap()
        if (refreshed !== null) await this.#runStream(publicKey, refreshed, message, false)
        return
      }
      throw error
    }
  }

  readonly #onEvent = (event: PublicStreamEvent): void => {
    switch (event.type) {
      case "start":
        this.#setStatus("Answering…")
        return
      case "token":
        this.#answer.append(document.createTextNode(event.token))
        return
      case "citations":
        this.#renderCitations(event.citations)
        return
      case "done":
        this.#input.value = ""
        this.#setStatus("Answer complete.")
        return
      default: {
        event satisfies never
        return
      }
    }
  }

  #renderCitations(citations: readonly PublicCitation[]): void {
    this.#citations.replaceChildren()
    for (const citation of citations) {
      const item = document.createElement("li")
      item.textContent =
        citation.page === undefined || citation.page === null
          ? citation.filename
          : `${citation.filename} · page ${citation.page}`
      this.#citations.append(item)
    }
  }

  async #cancelActive(): Promise<void> {
    const publicKey = this.#publicKey
    const proof = this.#proof
    if (!this.#streaming || publicKey === null || proof === null) return
    this.#streaming = false
    this.#setStatus("Response canceled.")
    try {
      await cancelPublicWidget(this.#baseUrl, publicKey, proof)
    } catch (error) {
      if (!(error instanceof PublicTransportError)) throw error
    }
  }

  #resetResponse(): void {
    this.#answer.replaceChildren()
    this.#citations.replaceChildren()
  }

  #setReady(ready: boolean): void {
    this.#send.disabled = !ready
  }

  #setStatus(message: string, retry = false): void {
    this.#status.textContent = message
    this.#retry.hidden = !retry
  }

  #showFailure(error: unknown, retry: boolean): void {
    this.#setReady(false)
    if (error instanceof PublicTransportError) {
      if (error.kind === "offline") {
        this.#setStatus("Chat is offline. Check your connection and try again.", retry)
        return
      }
      if (error.status === 403) {
        this.#setStatus("Chat is not available on this site.")
        return
      }
      if (error.status === 404) {
        this.#setStatus("Chat is currently unavailable.")
        return
      }
      if (error.status === 429) {
        const seconds = error.retryAfterSeconds
        this.#setStatus(
          seconds === null
            ? "Too many requests. Please try again later."
            : `Too many requests. Try again in ${seconds} seconds.`,
          retry,
        )
        return
      }
    }
    this.#setStatus("The response could not be completed. Please try again.", retry)
  }
}

if (customElements.get(WIDGET_ELEMENT_NAME) === undefined) {
  customElements.define(WIDGET_ELEMENT_NAME, WidgetElement)
}

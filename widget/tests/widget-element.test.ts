import { describe, expect, it } from "vitest"

import { WIDGET_ELEMENT_NAME, WidgetElement } from "../src/widget-element"
import { widgetStyles } from "../src/widget-styles"

function createWidget(): WidgetElement {
  const widget = document.createElement(WIDGET_ELEMENT_NAME)
  if (!(widget instanceof WidgetElement)) throw new TypeError("Widget registration failed")
  document.body.append(widget)
  return widget
}

function shadowButton(widget: WidgetElement, selector: string): HTMLButtonElement {
  const button = widget.shadowRoot?.querySelector<HTMLButtonElement>(selector)
  if (button === null || button === undefined) throw new TypeError(`Missing ${selector}`)
  return button
}

describe("RAG-Studio widget foundation", () => {
  it("registers one versioned custom element and renders only inside Shadow DOM", () => {
    const widget = createWidget()

    expect(customElements.get(WIDGET_ELEMENT_NAME)).toBe(WidgetElement)
    expect(widget.shadowRoot).not.toBeNull()
    expect(widget.children).toHaveLength(0)
    expect(document.querySelector(".rsw-panel")).toBeNull()
    expect(widget.shadowRoot?.querySelector(".rsw-panel")).not.toBeNull()
  })

  it("opens with the keyboard, traps focus, closes with Escape, and restores focus", () => {
    const widget = createWidget()
    const launcher = shadowButton(widget, ".rsw-launcher")
    launcher.focus()
    launcher.click()

    const close = shadowButton(widget, ".rsw-close")
    const input = widget.shadowRoot?.querySelector<HTMLTextAreaElement>("#rsw-question")
    expect(widget.hasAttribute("open")).toBe(true)
    expect(widget.shadowRoot?.activeElement).toBe(close)

    close.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, bubbles: true }))
    const retry = shadowButton(widget, ".rsw-retry")
    expect(widget.shadowRoot?.activeElement).toBe(retry)
    retry.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true }))
    expect(widget.shadowRoot?.activeElement).toBe(close)
    close.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true }))
    expect(widget.shadowRoot?.activeElement).toBe(input)
    input?.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true }))
    expect(widget.shadowRoot?.activeElement).toBe(retry)

    close.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }))
    expect(widget.hasAttribute("open")).toBe(false)
    expect(widget.shadowRoot?.activeElement).toBe(launcher)
  })

  it("reflects the documented open attribute without global overlays", () => {
    const widget = createWidget()
    widget.setAttribute("open", "")

    const dialog = widget.shadowRoot?.querySelector<HTMLElement>("[role='dialog']")
    expect(dialog?.getAttribute("aria-modal")).toBe("true")
    expect(dialog?.hasAttribute("hidden")).toBe(false)
    expect(document.querySelector("[role='dialog']")).toBeNull()

    widget.removeAttribute("open")
    expect(dialog?.hasAttribute("hidden")).toBe(true)
  })

  it("ships semantic tokens, 360px containment, focus, and reduced-motion rules", () => {
    expect(widgetStyles).toContain("--rsw-accent")
    expect(widgetStyles).toContain("--rsw-surface")
    expect(widgetStyles).toContain("--rsw-text")
    expect(widgetStyles).toContain("--rsw-radius")
    expect(widgetStyles).toContain("--rsw-font")
    expect(widgetStyles).toContain("@media (max-width: 400px)")
    expect(widgetStyles).toContain("@media (prefers-reduced-motion: reduce)")
    expect(widgetStyles).toContain(":focus-visible")
    expect(widgetStyles).not.toContain("backdrop-filter")
  })
})

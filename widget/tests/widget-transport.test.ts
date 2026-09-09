import { fireEvent, waitFor } from "@testing-library/dom"
import { afterEach, describe, expect, it, vi } from "vitest"
import {
  bootstrapPublicWidget,
  type PublicTransportError,
  streamPublicWidget,
} from "../src/public-transport"
import { WIDGET_ELEMENT_NAME, WidgetElement } from "../src/widget-element"

const KEY = "20000000-0000-4000-8000-000000000002"
const PROOF = {
  expires_at: "2026-08-25T12:15:00Z",
  proof: "signed-public-proof",
  session_id: "40000000-0000-4000-8000-000000000004",
}

function jsonResponse(body: unknown, status = 200, headers?: HeadersInit): Response {
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json", ...headers },
    status,
  })
}

function eventStream(...frames: readonly string[]): Response {
  return new Response(frames.join(""), {
    headers: { "Content-Type": "text/event-stream" },
    status: 200,
  })
}

function createWidget(): WidgetElement {
  const widget = document.createElement(WIDGET_ELEMENT_NAME)
  if (!(widget instanceof WidgetElement)) throw new TypeError("Widget registration failed")
  widget.setAttribute("widget-key", KEY)
  document.body.append(widget)
  return widget
}

function requireShadow<T extends Element>(widget: WidgetElement, selector: string): T {
  const element = widget.shadowRoot?.querySelector<T>(selector)
  if (element === null || element === undefined) throw new TypeError(`Missing ${selector}`)
  return element
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("public widget transport", () => {
  it("parses the public bootstrap boundary", async () => {
    const fetch = vi.fn<typeof globalThis.fetch>().mockResolvedValue(jsonResponse(PROOF))
    vi.stubGlobal("fetch", fetch)

    const bootstrap = bootstrapPublicWidget("http://localhost:3000", KEY)
    await expect(bootstrap).resolves.toEqual(PROOF)
    expect(fetch).toHaveBeenCalledOnce()
  })
  it("Given an approved host, streams ordered text, safe citations, and a terminal state", async () => {
    const fetch = vi
      .fn<typeof globalThis.fetch>()
      .mockResolvedValueOnce(jsonResponse(PROOF))
      .mockResolvedValueOnce(jsonResponse(PROOF))
      .mockResolvedValueOnce(
        eventStream(
          'event: start\ndata: {"protocol":"1"}\n\n',
          'event: token\ndata: {"token":"grounded "}\n\n',
          'event: token\ndata: {"token":"answer"}\n\n',
          'event: citations\ndata: {"citations":[{"filename":"guide.pdf","page":2}]}\n\n',
          'event: done\ndata: {"done":true}\n\n',
        ),
      )
    vi.stubGlobal("fetch", fetch)
    const widget = createWidget()

    await waitFor(() =>
      expect(requireShadow<HTMLButtonElement>(widget, ".rsw-send").disabled).toBe(false),
    )
    widget.setAttribute("open", "")
    const close = requireShadow<HTMLButtonElement>(widget, ".rsw-close")
    const input = requireShadow<HTMLTextAreaElement>(widget, "#rsw-question")
    const send = requireShadow<HTMLButtonElement>(widget, ".rsw-send")
    close.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "Tab" }))
    expect(widget.shadowRoot?.activeElement).toBe(input)
    input.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "Tab" }))
    expect(widget.shadowRoot?.activeElement).toBe(send)
    send.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "Tab" }))
    expect(widget.shadowRoot?.activeElement).toBe(close)
    input.value = "What is grounded?"
    fireEvent.submit(requireShadow<HTMLFormElement>(widget, ".rsw-composer"))

    await waitFor(() =>
      expect(requireShadow(widget, ".rsw-status").textContent).toBe("Answer complete."),
    )
    expect(requireShadow(widget, ".rsw-answer").textContent).toBe("grounded answer")
    expect(requireShadow(widget, ".rsw-citations").textContent).toContain("guide.pdf · page 2")
    expect(requireShadow(widget, ".rsw-citations").textContent).not.toContain("scope")
    expect(fetch.mock.calls.map(([input]) => String(input))).toEqual([
      expect.stringContaining(`/api/public/widgets/${KEY}/proof`),
      expect.stringContaining(`/api/public/widgets/${KEY}/proof`),
      expect.stringContaining(`/api/public/widgets/${KEY}/streams`),
    ])
  })

  it("Given an expired proof, refreshes once through bootstrap and never reconnects unbounded", async () => {
    const fresh = { ...PROOF, proof: "fresh-proof" }
    const fetch = vi
      .fn<typeof globalThis.fetch>()
      .mockResolvedValueOnce(jsonResponse(PROOF))
      .mockResolvedValueOnce(jsonResponse(PROOF))
      .mockResolvedValueOnce(jsonResponse({ detail: "private detail" }, 401))
      .mockResolvedValueOnce(jsonResponse(fresh))
      .mockResolvedValueOnce(
        eventStream(
          'event: start\ndata: {"protocol":"1"}\n\nevent: citations\ndata: {"citations":[]}\n\nevent: done\ndata: {"done":true}\n\n',
        ),
      )
    vi.stubGlobal("fetch", fetch)
    const widget = createWidget()

    await waitFor(() =>
      expect(requireShadow<HTMLButtonElement>(widget, ".rsw-send").disabled).toBe(false),
    )
    requireShadow<HTMLTextAreaElement>(widget, "#rsw-question").value = "Retry safely"
    fireEvent.submit(requireShadow<HTMLFormElement>(widget, ".rsw-composer"))

    await waitFor(() =>
      expect(requireShadow(widget, ".rsw-status").textContent).toBe("Answer complete."),
    )
    expect(requireShadow(widget, ".rsw-status").textContent).not.toBe(
      "The response could not be completed. Please try again.",
    )
    expect(fetch).toHaveBeenCalledTimes(5)
    expect(requireShadow(widget, ".rsw-content").textContent).not.toContain("private detail")
  })

  it.each([
    [403, "not available on this site"],
    [404, "currently unavailable"],
    [429, "Try again in 9 seconds"],
  ])("Given public rejection %i, renders a sanitized accessible state", async (status, message) => {
    const headers = status === 429 ? { "Retry-After": "9" } : undefined
    vi.stubGlobal(
      "fetch",
      vi
        .fn<typeof globalThis.fetch>()
        .mockResolvedValue(jsonResponse({ detail: "scope/private/path" }, status, headers)),
    )
    const widget = createWidget()

    await waitFor(() => expect(requireShadow(widget, ".rsw-status").textContent).toContain(message))
    expect(requireShadow(widget, ".rsw-content").textContent).not.toMatch(/scope|private|path/i)
    expect(requireShadow<HTMLButtonElement>(widget, ".rsw-send").disabled).toBe(true)
  })

  it("Given offline transport, preserves the host and offers a bounded retry", async () => {
    const host = document.createElement("p")
    host.textContent = "Host content"
    document.body.append(host)
    const fetch = vi
      .fn<typeof globalThis.fetch>()
      .mockRejectedValue(new TypeError("offline/private"))
    vi.stubGlobal("fetch", fetch)
    const widget = createWidget()

    await waitFor(() =>
      expect(requireShadow(widget, ".rsw-status").textContent).toContain("offline"),
    )
    expect(host.textContent).toBe("Host content")
    expect(widget.children).toHaveLength(0)
    expect(requireShadow(widget, ".rsw-content").textContent).not.toContain("offline/private")
    widget.setAttribute("open", "")
    const close = requireShadow<HTMLButtonElement>(widget, ".rsw-close")
    const input = requireShadow<HTMLTextAreaElement>(widget, "#rsw-question")
    const retry = requireShadow<HTMLButtonElement>(widget, ".rsw-retry")
    close.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "Tab" }))
    input.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "Tab" }))
    expect(widget.shadowRoot?.activeElement).toBe(retry)
    fireEvent.click(requireShadow(widget, ".rsw-retry"))
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2))
  })

  it.each([
    [
      'event: token\ndata: {"token":"early"}\n\nevent: start\ndata: {"protocol":"1"}\n\n',
      "token before start",
    ],
    [
      'event: start\ndata: {"protocol":"1"}\n\nevent: done\ndata: {"done":true}\n\n',
      "done before citations",
    ],
    [
      'event: start\ndata: {"protocol":"1"}\n\nevent: citations\ndata: {"citations":[]}\n\nevent: done\ndata: {"done":true}\n\nevent: token\ndata: {"token":"late"}\n\n',
      "event after done",
    ],
  ])("rejects %s instead of rendering reordered stream data", async (frames) => {
    const fetch = vi.fn<typeof globalThis.fetch>().mockResolvedValue(eventStream(frames))
    vi.stubGlobal("fetch", fetch)
    const events: string[] = []

    await expect(
      streamPublicWidget("http://localhost:3000", KEY, PROOF, "question", (event) => {
        events.push(event.type)
      }),
    ).rejects.toEqual(expect.objectContaining<Partial<PublicTransportError>>({ kind: "protocol" }))
    expect(events).not.toContain("token")
  })

  it("Given an active stream, close issues only the proof-bound public cancel call", async () => {
    let releaseStream: (() => void) | undefined
    const pendingStream = new Promise<Response>((resolve) => {
      releaseStream = () =>
        resolve(
          eventStream(
            'event: error\ndata: {"code":"canceled","message":"ignored","retryable":true}\n\n',
          ),
        )
    })
    const fetch = vi
      .fn<typeof globalThis.fetch>()
      .mockResolvedValueOnce(jsonResponse(PROOF))
      .mockResolvedValueOnce(jsonResponse(PROOF))
      .mockReturnValueOnce(pendingStream)
      .mockResolvedValueOnce(jsonResponse({ status: "stopped" }))
    vi.stubGlobal("fetch", fetch)
    const widget = createWidget()

    await waitFor(() =>
      expect(requireShadow<HTMLButtonElement>(widget, ".rsw-send").disabled).toBe(false),
    )
    requireShadow<HTMLTextAreaElement>(widget, "#rsw-question").value = "Stop"
    fireEvent.submit(requireShadow<HTMLFormElement>(widget, ".rsw-composer"))
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(3))
    fireEvent.click(requireShadow(widget, ".rsw-close"))
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(4))

    expect(String(fetch.mock.calls[3]?.[0])).toContain(
      `/api/public/widgets/${KEY}/streams/${PROOF.session_id}/cancel`,
    )
    expect(document.body.textContent).not.toContain(PROOF.proof)
    releaseStream?.()
  })
})

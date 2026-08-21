import { afterEach, describe, expect, it, vi } from "vitest"

import { streamChat } from "./stream"

function emptyStream(): Response {
  const body = new ReadableStream<Uint8Array>({ start: (controller) => controller.close() })
  return new Response(body, { headers: { "Content-Type": "text/event-stream" } })
}

describe("stream CSRF recovery", () => {
  afterEach(() => vi.unstubAllGlobals())

  it("renews expired CSRF state before starting the protected chat stream", async () => {
    // Given: an active session whose readable CSRF cookie has expired.
    const documentStub = { cookie: "" }
    vi.stubGlobal("document", documentStub)
    const fetchSpy = vi.fn((input: string) => {
      if (input === "/api/saas/auth/csrf") {
        documentStub.cookie = "__Host-ragstudio-csrf=renewed-proof"
        return Promise.resolve(new Response(null, { status: 204 }))
      }
      return Promise.resolve(emptyStream())
    })
    vi.stubGlobal("fetch", fetchSpy)

    // When: Personal Lab starts its protected POST stream.
    await streamChat(
      { content: "question" },
      { onEvent: vi.fn(), signal: new AbortController().signal },
    )

    // Then: the BFF proof endpoint runs first and the stream carries the renewed proof.
    expect(fetchSpy.mock.calls.map(([input]) => input)).toEqual([
      "/api/saas/auth/csrf",
      "/api/chat/send",
    ])
    expect(fetchSpy).toHaveBeenLastCalledWith(
      "/api/chat/send",
      expect.objectContaining({
        headers: expect.objectContaining({ "X-CSRF-Token": "renewed-proof" }),
        method: "POST",
      }),
    )
  })
})

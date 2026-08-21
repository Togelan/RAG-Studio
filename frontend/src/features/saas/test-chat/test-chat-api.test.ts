import { afterEach, describe, expect, it, vi } from "vitest"

import { createTestChatStreamGateway } from "./test-chat-api"

function emptyStream(): Response {
  const body = new ReadableStream<Uint8Array>({ start: (controller) => controller.close() })
  return new Response(body, { headers: { "Content-Type": "text/event-stream" } })
}

describe("test chat stream gateway", () => {
  afterEach(() => vi.unstubAllGlobals())

  it("uses the shared local-development CSRF proof for the protected stream", async () => {
    // Given: local HTTP development cookies and a streaming request implementation.
    vi.stubGlobal("document", {
      cookie:
        "ragstudio-development-session=development-session; ragstudio-development-csrf=local-proof",
    })
    const fetchImplementation = vi.fn(() => Promise.resolve(emptyStream()))
    const gateway = createTestChatStreamGateway(undefined, fetchImplementation)

    // When: Test Chat sends a protected message stream.
    await gateway.send(
      "workspace-id",
      "chatbot-id",
      "session-id",
      { content: "question", locale: "en" },
      { onEvent: vi.fn(), signal: new AbortController().signal },
    )

    // Then: the stream carries the readable development CSRF proof.
    expect(fetchImplementation).toHaveBeenCalledOnce()
    expect(fetchImplementation).toHaveBeenCalledWith(
      "/api/saas/workspaces/workspace-id/chatbots/chatbot-id/sessions/session-id/messages",
      expect.objectContaining({
        headers: expect.objectContaining({ "X-CSRF-Token": "local-proof" }),
        method: "POST",
      }),
    )
  })
})

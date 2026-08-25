import { afterEach, describe, expect, it, vi } from "vitest"
import { z } from "zod"

import { ApiClient, type KyHttpClient, type KyRequestOptions } from "../../api/client"
import { bindBrowserFetch, createChatGateway } from "./chat-api"

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("createChatGateway", () => {
  it("binds the browser fetch receiver for the default client", async () => {
    const browser = globalThis
    const receiverAwareFetch = vi.fn(function (this: typeof globalThis) {
      if (this !== browser) {
        throw new TypeError("Illegal invocation")
      }
      return Promise.resolve(Response.json([]))
    })
    await expect(bindBrowserFetch(receiverAwareFetch)("/api/test")).resolves.toEqual(
      expect.any(Response),
    )
    expect(receiverAwareFetch.mock.instances[0]).toBe(browser)
  })

  it("uses only scoped Personal Chat paths and translates feedback values at the boundary", async () => {
    // Given: an HTTP seam that records every requested path.
    const requests: Array<{ readonly input: string; readonly options: KyRequestOptions }> = []
    const responseFor = (input: string): Response => {
      if (input.endsWith("/feedback")) {
        return Response.json({ feedback: "like", id: "feedback-a", status: "saved" })
      }
      return Response.json([])
    }
    const request = (input: string, options: KyRequestOptions): Promise<Response> => {
      requests.push({ input, options })
      return Promise.resolve(responseFor(input))
    }
    const http: KyHttpClient = { delete: request, get: request, patch: request, post: request }
    const client = new ApiClient(fetch, http, () => "csrf-proof")
    const gateway = createChatGateway(client)

    // When: history and positive feedback cross the browser boundary.
    await gateway.listSessions()
    await expect(
      gateway.feedback({
        feedback: "positive",
        message_id: "assistant-a",
        session_id: "session-a",
      }),
    ).resolves.toEqual({ feedback: "positive", status: "saved" })

    // Then: no host-global route is called and the backend receives its scoped vocabulary.
    expect(requests.map(({ input }) => input)).toEqual([
      "/api/personal/chat/sessions",
      "/api/personal/chat/feedback",
    ])
    expect(requests[1]?.options.json).toEqual({
      feedback: "like",
      message_id: "assistant-a",
      session_id: "session-a",
    })
    expect(z.string().parse(requests[0]?.input)).not.toMatch(/^\/api\/chat\//u)
  })
})

import { afterEach, describe, expect, it, vi } from "vitest"
import { bindBrowserFetch } from "./chat-api"

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
})

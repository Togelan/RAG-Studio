import { afterEach, describe, expect, it, vi } from "vitest"
import { z } from "zod"

import type { KyHttpClient, KyRequestOptions } from "./client"
import { ApiClient } from "./client"

type RecordedRequest = {
  readonly input: string
  readonly options: KyRequestOptions
}

function recordingHttp(
  responseFor: (input: string) => Response,
  requests: RecordedRequest[],
): KyHttpClient {
  const request = (input: string, options: KyRequestOptions): Promise<Response> => {
    requests.push({ input, options })
    return Promise.resolve(responseFor(input))
  }

  return { delete: request, get: request, patch: request, post: request, put: request }
}

describe("SaaS ApiClient boundary", () => {
  afterEach(() => vi.unstubAllGlobals())

  it("keeps the browser Window receiver when the default fetch executes", async () => {
    // Given: a browser fetch implementation that rejects when detached from its Window receiver.
    const receiverSensitiveFetch = vi.fn(function (this: typeof globalThis) {
      if (this !== globalThis) {
        throw new TypeError("Illegal invocation")
      }
      return Promise.resolve(new Response("[]"))
    }) as unknown as typeof fetch
    const NativeRequest = Request
    vi.stubGlobal(
      "Request",
      class BrowserRequest extends NativeRequest {
        constructor(input: RequestInfo | URL, init?: RequestInit) {
          super(typeof input === "string" ? new URL(input, window.location.href) : input, init)
        }
      },
    )
    vi.stubGlobal("fetch", receiverSensitiveFetch)
    const client = new ApiClient()

    // When: the default client requests a SaaS collection through ky.
    const result = await client.get("/api/saas/workspaces", z.array(z.unknown()))

    // Then: the browser method retains its receiver and the response reaches the contract parser.
    expect(result).toEqual([])
    expect(receiverSensitiveFetch).toHaveBeenCalledOnce()
  })

  it("adds double-submit CSRF proof internally for unsafe SaaS requests", async () => {
    // Given: a browser-readable CSRF cookie and an opaque session managed by the BFF.
    const requests: RecordedRequest[] = []
    const client = new ApiClient(
      fetch,
      recordingHttp(
        () => new Response('{"confirmation_required":false}', { status: 201 }),
        requests,
      ),
      () => "csrf-proof",
    )

    // When: application code submits a SaaS mutation without handling cookies.
    await client.post(
      "/api/saas/auth/signup",
      { email: "owner@example.test", password: "correct-horse" },
      z.object({ confirmation_required: z.boolean() }),
    )

    // Then: the client supplies the double-submit header without exposing auth state.
    expect(requests).toHaveLength(1)
    expect(requests[0]?.options.headers).toEqual({ "X-CSRF-Token": "csrf-proof" })
  })

  it("establishes missing CSRF state once before the mutation", async () => {
    // Given: no current CSRF cookie until the BFF establishment endpoint responds.
    const requests: RecordedRequest[] = []
    const token = vi.fn<() => string | null>()
    token.mockReturnValueOnce(null).mockReturnValue("established-proof")
    const client = new ApiClient(
      fetch,
      recordingHttp(
        (input) =>
          input.endsWith("/csrf")
            ? new Response(null, { status: 204 })
            : new Response(
                '{"user_id":"00000000-0000-4000-8000-000000000001","email":"owner@example.test","workspace":null}',
              ),
        requests,
      ),
      token,
    )

    // When: the first unsafe request is issued.
    await client.post(
      "/api/saas/auth/signin",
      { email: "owner@example.test", password: "correct-horse" },
      z.object({
        user_id: z.string().uuid(),
        email: z.string().email(),
        workspace: z.null(),
      }),
    )

    // Then: CSRF is established before the request and used exactly at the boundary.
    expect(requests.map(({ input }) => input)).toEqual([
      "/api/saas/auth/csrf",
      "/api/saas/auth/signin",
    ])
    expect(requests[1]?.options.headers).toEqual({
      "X-CSRF-Token": "established-proof",
    })
  })

  it.each(["/api/settings", "/api/ingest/documents", "/api/chat/sessions"])(
    "adds CSRF proof for protected Personal Lab mutations at %s",
    async (path) => {
      const requests: RecordedRequest[] = []
      const client = new ApiClient(
        fetch,
        recordingHttp(() => new Response("{}", { status: 200 }), requests),
        () => "csrf-proof",
      )

      await client.post(path, {}, z.object({}).strict())

      expect(requests[0]?.options.headers).toEqual({ "X-CSRF-Token": "csrf-proof" })
    },
  )

  it("refreshes stale CSRF proof after one rejected Personal mutation", async () => {
    const requests: RecordedRequest[] = []
    let proof = "stale-proof"
    let mutationCount = 0
    const client = new ApiClient(
      fetch,
      recordingHttp((input) => {
        if (input === "/api/saas/auth/csrf") {
          proof = "fresh-proof"
          return new Response(null, { status: 204 })
        }
        mutationCount += 1
        return new Response("{}", { status: mutationCount === 1 ? 403 : 200 })
      }, requests),
      () => proof,
    )

    await client.post("/api/personal/settings", {}, z.object({}).strict())

    expect(requests.map(({ input }) => input)).toEqual([
      "/api/personal/settings",
      "/api/saas/auth/csrf",
      "/api/personal/settings",
    ])
    expect(requests[0]?.options.throwHttpErrors).toBe(false)
    expect(requests[2]?.options.throwHttpErrors).toBe(false)
    expect(requests[2]?.options.headers).toEqual({ "X-CSRF-Token": "fresh-proof" })
  })

  it("keeps multipart upload timeout and cancellation bounds after stale CSRF recovery", async () => {
    // Given: a long upload whose first mutation is rejected by stale CSRF state.
    const requests: RecordedRequest[] = []
    const signal = new AbortController().signal
    let proof = "stale-proof"
    let mutationCount = 0
    const client = new ApiClient(
      fetch,
      recordingHttp((input) => {
        if (input === "/api/saas/auth/csrf") {
          proof = "fresh-proof"
          return new Response(null, { status: 204 })
        }
        mutationCount += 1
        return new Response("{}", { status: mutationCount === 1 ? 403 : 200 })
      }, requests),
      () => proof,
    )

    // When: the multipart request performs its single CSRF recovery retry.
    await client.postFormResponse("/api/personal/knowledge/upload", new FormData(), { signal })

    // Then: both attempts preserve the five-minute wall clock and caller cancellation bounds.
    expect(requests.map(({ input }) => input)).toEqual([
      "/api/personal/knowledge/upload",
      "/api/saas/auth/csrf",
      "/api/personal/knowledge/upload",
    ])
    expect(requests[0]?.options).toMatchObject({ signal, timeout: 300_000 })
    expect(requests[2]?.options).toMatchObject({
      headers: { "X-CSRF-Token": "fresh-proof" },
      signal,
      timeout: 300_000,
    })
  })

  it.each(["/api/settings", "/api/ingest/documents", "/api/chat/sessions"])(
    "renews expired CSRF state before protected Personal Lab mutations at %s",
    async (path) => {
      // Given: a long-lived BFF session whose short-lived CSRF companion expired.
      const requests: RecordedRequest[] = []
      const token = vi.fn<() => string | null>()
      token.mockReturnValueOnce(null).mockReturnValue("renewed-proof")
      const client = new ApiClient(
        fetch,
        recordingHttp(
          (input) =>
            input === "/api/saas/auth/csrf"
              ? new Response(null, { status: 204 })
              : new Response("{}", { status: 200 }),
          requests,
        ),
        token,
      )

      // When: Personal Lab performs its next protected mutation.
      await client.post(path, {}, z.object({}).strict())

      // Then: the BFF refreshes proof first and the mutation receives it.
      expect(requests.map(({ input }) => input)).toEqual(["/api/saas/auth/csrf", path])
      expect(requests[1]?.options.headers).toEqual({ "X-CSRF-Token": "renewed-proof" })
    },
  )

  it("supports PUT, DELETE bodies, and valid empty responses", async () => {
    // Given: SaaS endpoints that rotate workspace context and archive by version.
    const requests: RecordedRequest[] = []
    const client = new ApiClient(
      fetch,
      recordingHttp(
        (input) =>
          input.endsWith("/workspace")
            ? new Response(
                '{"user_id":"00000000-0000-4000-8000-000000000001","email":"owner@example.test","workspace":{"id":"00000000-0000-4000-8000-000000000010","role":"owner"}}',
              )
            : new Response(null, { status: 204 }),
        requests,
      ),
      () => "csrf-proof",
    )

    // When: the typed client performs the two route-specific mutations.
    await client.put(
      "/api/saas/auth/workspace",
      { workspace_id: "00000000-0000-4000-8000-000000000010" },
      z.object({
        user_id: z.string().uuid(),
        email: z.string().email(),
        workspace: z.object({ id: z.string().uuid(), role: z.literal("owner") }),
      }),
    )
    await client.delete(
      "/api/saas/workspaces/00000000-0000-4000-8000-000000000010/chatbots/00000000-0000-4000-8000-000000000020",
      z.undefined(),
      { body: { version: 3 } },
    )

    // Then: both use CSRF, the DELETE body is retained, and 204 parses as undefined.
    expect(requests[0]?.options.headers).toEqual({ "X-CSRF-Token": "csrf-proof" })
    expect(requests[1]?.options).toMatchObject({
      headers: { "X-CSRF-Token": "csrf-proof" },
      json: { version: 3 },
    })
  })

  it("sends multipart SaaS uploads with CSRF proof and no forced content type", async () => {
    // Given: a source file selected by an authenticated workspace manager.
    const requests: RecordedRequest[] = []
    const client = new ApiClient(
      fetch,
      recordingHttp(
        () => new Response('{"doc_id":"document-id","chunk_count":1}', { status: 201 }),
        requests,
      ),
      () => "csrf-proof",
    )
    const payload = new FormData()
    payload.set("file", new File(["source text"], "handbook.md", { type: "text/markdown" }))

    // When: the application uploads the source through the shared API boundary.
    const result = await client.postForm(
      "/api/saas/workspaces/00000000-0000-4000-8000-000000000010/documents/upload",
      payload,
      z.object({ doc_id: z.string(), chunk_count: z.number().int() }),
    )

    // Then: the multipart body and CSRF proof reach the BFF without a JSON content type.
    expect(result).toEqual({ doc_id: "document-id", chunk_count: 1 })
    expect(requests[0]?.options).toMatchObject({
      body: payload,
      headers: { "X-CSRF-Token": "csrf-proof" },
    })
    expect(requests[0]?.options.headers).not.toHaveProperty("Content-Type")
  })
})

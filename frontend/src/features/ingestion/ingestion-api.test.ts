import { describe, expect, it, vi } from "vitest"

import { ApiClient, type KyHttpClient } from "../../api/client"
import { ApiError } from "../../api/errors"
import {
  bindBrowserFetch,
  createIngestionApi,
  reingestSequentially,
  type UploadTransport,
} from "./ingestion-api"

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), { headers: { "Content-Type": "application/json" } })
}

function httpClient(overrides: Partial<KyHttpClient> = {}): KyHttpClient {
  return {
    delete: vi.fn(),
    get: vi.fn(),
    patch: vi.fn(),
    post: vi.fn(),
    ...overrides,
  }
}

describe("ingestion API contract", () => {
  it("binds browser fetch before constructing the feature gateway", async () => {
    const browserFetch = vi.fn(function (this: typeof globalThis) {
      expect(this).toBe(globalThis)
      return Promise.resolve(jsonResponse({}))
    }) as unknown as typeof fetch

    await bindBrowserFetch(browserFetch)("/api/personal/knowledge/documents")

    expect(browserFetch).toHaveBeenCalledOnce()
  })

  it("uses an encoded cursor and preserves the bounded continuation contract", async () => {
    const get = vi.fn(() =>
      Promise.resolve(
        jsonResponse({
          documents: [
            { doc_id: "doc-1", filename: "safe.txt", chunk_count: 2, strategy: "recursive" },
          ],
          next_cursor: "next/cursor+value",
          truncated: true,
        }),
      ),
    )
    const http: KyHttpClient = { delete: vi.fn(), get, patch: vi.fn(), post: vi.fn() }
    const api = createIngestionApi(new ApiClient(fetch, http), vi.fn())

    const page = await api.documents("first/cursor+value")

    expect(get).toHaveBeenCalledWith(
      "/api/personal/knowledge/documents?cursor=first%2Fcursor%2Bvalue",
      {},
    )
    expect(page.truncated).toBe(true)
    expect(page.next_cursor).toBe("next/cursor+value")
    expect(page.documents[0]).toMatchObject({ chunks_count: 2, filename: "safe.txt" })
  })

  it("uses the exact chunks, progress, re-ingest, delete, and clear contracts", async () => {
    const get = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({
          chunks: [
            {
              point_id: "point-1",
              text: "Scoped content",
              chunk_index: 0,
              strategy: "recursive",
              csv_row: null,
            },
          ],
          next_cursor: "next",
          truncated: true,
        }),
      )
      .mockResolvedValueOnce(jsonResponse({ file_id: "job/1", status: "complete", code: null }))
    const post = vi.fn(() =>
      Promise.resolve(jsonResponse({ status: "processing", file_id: "job", message: "queued" })),
    )
    const remove = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ deleted: 1 }))
      .mockResolvedValueOnce(jsonResponse({ deleted: 3 }))
    const api = createIngestionApi(
      new ApiClient(fetch, httpClient({ delete: remove, get, post }), () => "csrf-proof"),
      vi.fn(),
    )
    const signal = new AbortController().signal

    const chunks = await api.chunks("doc/1", "chunk/+", signal)
    const progress = await api.progress("job/1", signal)
    await api.reingest({ doc_id: "doc-1", filename: "safe.txt" }, signal)
    await api.deleteDocument("doc/1", signal)
    await api.clear(signal)

    expect(chunks.chunks[0]).toMatchObject({ point_id: "point-1", strategy: "recursive" })
    expect(progress.status).toBe("done")

    expect(get).toHaveBeenNthCalledWith(
      1,
      "/api/personal/knowledge/documents/doc%2F1/chunks?cursor=chunk%2F%2B",
      { signal },
    )
    expect(get).toHaveBeenNthCalledWith(2, "/api/personal/knowledge/progress/job%2F1", { signal })
    expect(post).toHaveBeenCalledWith("/api/personal/knowledge/documents/doc-1/reindex", {
      headers: { "X-CSRF-Token": "csrf-proof" },
      json: {},
      retry: 0,
      signal,
      throwHttpErrors: false,
    })
    expect(remove).toHaveBeenNthCalledWith(1, "/api/personal/knowledge/documents/doc%2F1", {
      headers: { "X-CSRF-Token": "csrf-proof" },
      retry: 0,
      signal,
      throwHttpErrors: false,
    })
    expect(remove).toHaveBeenNthCalledWith(2, "/api/personal/knowledge/clear", {
      headers: { "X-CSRF-Token": "csrf-proof" },
      retry: 0,
      signal,
      throwHttpErrors: false,
    })
  })

  it.each(["default", "cancel", "rename", "replace"] as const)(
    "uploads a multipart file with the %s duplicate action",
    async (action) => {
      const upload = vi.fn<UploadTransport>(() =>
        Promise.resolve(
          jsonResponse({
            status: action === "cancel" ? "cancelled" : "unchanged",
            file_id: "",
            message: "ok",
          }),
        ),
      )
      const api = createIngestionApi(new ApiClient(fetch, httpClient()), upload)
      const file = new File(["hello"], "hello.txt", { type: "text/plain" })
      const signal = new AbortController().signal

      await api.upload(file, action, signal)

      const expectedPath =
        action === "default"
          ? "/api/personal/knowledge/upload"
          : `/api/personal/knowledge/upload?action=${action}`
      expect(upload).toHaveBeenCalledWith(expectedPath, expect.any(FormData), signal)
      const body = vi.mocked(upload).mock.calls[0]?.[1]
      const uploadedFile = body?.get("file")
      expect(uploadedFile).toBeInstanceOf(File)
      expect((uploadedFile as File).name).toBe("hello.txt")
    },
  )

  it("uses the shared CSRF transport for multipart Personal uploads", async () => {
    const post = vi.fn(() =>
      Promise.resolve(jsonResponse({ status: "unchanged", file_id: "", message: "ready" })),
    )
    const api = createIngestionApi(
      new ApiClient(fetch, httpClient({ post }), () => "personal-csrf-proof"),
    )

    await api.upload(new File(["hello"], "hello.txt", { type: "text/plain" }))

    expect(post).toHaveBeenCalledWith(
      "/api/personal/knowledge/upload",
      expect.objectContaining({
        body: expect.any(FormData),
        headers: { "X-CSRF-Token": "personal-csrf-proof" },
        retry: 0,
      }),
    )
  })

  it("parses the duplicate 409 contract without treating it as a retry", async () => {
    const upload = vi.fn(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            status: "duplicate",
            filename: "same.txt",
            existing_chunks: 2,
            existing_size: 10,
            stored_chunk_size: 512,
            stored_chunk_overlap: 64,
            new_file_size: 12,
            estimated_chunks: 3,
            chunks_settings_changed: false,
            current_chunk_size: 512,
            current_chunk_overlap: 64,
          }),
          { status: 409 },
        ),
      ),
    )
    const api = createIngestionApi(new ApiClient(fetch, httpClient()), upload)

    await expect(api.upload(new File(["x"], "same.txt"))).resolves.toMatchObject({
      kind: "duplicate",
      response: { filename: "same.txt" },
    })
    expect(upload).toHaveBeenCalledOnce()
  })

  it.each([400, 404, 422, 429, 503])(
    "maps upload status %s to a sanitized error and performs no retry",
    async (status) => {
      const upload = vi.fn(() =>
        Promise.resolve(new Response("provider path and secret", { status })),
      )
      const api = createIngestionApi(new ApiClient(fetch, httpClient()), upload)

      const error = await api.upload(new File(["x"], "safe.txt")).catch((caught: unknown) => caught)

      expect(error).toBeInstanceOf(ApiError)
      expect((error as ApiError).message).not.toContain("provider")
      expect(upload).toHaveBeenCalledOnce()
    },
  )

  it("continues a re-ingest batch after a skipped item and a failure", async () => {
    const documents = [
      { doc_id: "doc-a", filename: "a.txt" },
      { doc_id: "doc-b", filename: "b.txt" },
      { doc_id: "doc-c", filename: "c.txt" },
    ] as const
    const reingest = vi
      .fn()
      .mockResolvedValueOnce({ status: "processing", file_id: "job-a", message: "queued" })
      .mockResolvedValueOnce({ status: "skipped", file_id: "doc-b", message: "missing" })
      .mockRejectedValueOnce(new Error("transport failed"))
    const updates: number[] = []

    const result = await reingestSequentially(documents, reingest, (completed) => {
      updates.push(completed)
    })

    expect(reingest).toHaveBeenCalledTimes(3)
    expect(result).toEqual({ failed: 1, skipped: 1, succeeded: 1, total: 3 })
    expect(updates).toEqual([1, 2, 3])
  })
})

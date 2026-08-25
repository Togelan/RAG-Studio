import { describe, expect, it, vi } from "vitest"

import { ApiClient, type KyHttpClient } from "../../api/client"
import { ApiError } from "../../api/errors"
import { bindBrowserFetch, createSettingsApi, SettingsResponseSchema } from "./settings-api"

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), { headers: { "Content-Type": "application/json" } })
}

const chunking = {
  schema_version: 1,
  strategy: "recursive",
  chunk_size: 512,
  chunk_overlap: 64,
  parent_size: 2048,
  window_sentences: 2,
} as const

describe("settings API contract", () => {
  it("binds browser fetch before constructing the feature gateway", async () => {
    const browserFetch = vi.fn(function (this: typeof globalThis) {
      expect(this).toBe(globalThis)
      return Promise.resolve(jsonResponse({}))
    }) as unknown as typeof fetch

    await bindBrowserFetch(browserFetch)("/api/personal/settings")

    expect(browserFetch).toHaveBeenCalledOnce()
  })

  it("accepts the backend defaults for inactive chunk-strategy fields", () => {
    expect(
      SettingsResponseSchema.safeParse({
        api_key: null,
        chunk_overlap: 64,
        chunk_size: 512,
        chunking: { ...chunking, parent_size: null, window_sentences: null },
        max_tokens: 2048,
        model: "gpt-4o-mini",
        provider: "deepseek",
        system_prompt: "Answer from context.",
        temperature: 1,
        top_k: 5,
      }).success,
    ).toBe(true)
  })

  it("loads masked credentials and atomically saves a replacement key with settings", async () => {
    const settings = {
      provider: "deepseek",
      model: "deepseek-chat",
      temperature: 1,
      max_tokens: 2048,
      system_prompt: "Answer from context.",
      top_k: 5,
      chunk_size: 512,
      chunk_overlap: 64,
      chunking,
    } as const
    const get = vi.fn(() => Promise.resolve(jsonResponse({ ...settings, api_key: "********" })))
    const post = vi.fn(() => Promise.resolve(jsonResponse({ ...settings, chunks_changed: false })))
    const http: KyHttpClient = { delete: vi.fn(), get, patch: vi.fn(), post }
    const api = createSettingsApi(new ApiClient(fetch, http, () => "csrf-proof"))

    const loaded = await api.load()
    await api.save(settings, "replacement-secret")

    expect(loaded.api_key).toBe("********")
    expect(post).toHaveBeenCalledWith(
      "/api/personal/settings",
      expect.objectContaining({
        json: { ...settings, api_key: "replacement-secret" },
        retry: 0,
      }),
    )
  })

  it("omits the credential field when the stored masked key is unchanged", async () => {
    const settings = {
      provider: "deepseek",
      model: "deepseek-chat",
      temperature: 1,
      max_tokens: 2048,
      system_prompt: "Answer from context.",
      top_k: 5,
      chunk_size: 512,
      chunk_overlap: 64,
      chunking,
    } as const
    const post = vi.fn(() => Promise.resolve(jsonResponse({ ...settings, chunks_changed: false })))
    const http: KyHttpClient = { delete: vi.fn(), get: vi.fn(), patch: vi.fn(), post }

    await createSettingsApi(new ApiClient(fetch, http, () => "csrf-proof")).save(settings)

    expect(post).toHaveBeenCalledWith(
      "/api/personal/settings",
      expect.objectContaining({
        json: expect.not.objectContaining({ api_key: expect.anything() }),
        retry: 0,
      }),
    )
  })

  it("keeps credential validation and model refresh on their exact endpoints", async () => {
    const get = vi.fn(() =>
      Promise.resolve(
        jsonResponse({ provider: "deepseek", models: ["deepseek-chat"], cached: true }),
      ),
    )
    const post = vi.fn(() =>
      Promise.resolve(jsonResponse({ valid: true, provider: "deepseek", error: null })),
    )
    const http: KyHttpClient = { delete: vi.fn(), get, patch: vi.fn(), post }
    const api = createSettingsApi(new ApiClient(fetch, http, () => "csrf-proof"))

    await api.validateKey("deepseek", "secret-value")
    const result = await api.models("deepseek")

    expect(post).toHaveBeenCalledWith(
      "/api/personal/settings/validate-key",
      expect.objectContaining({
        json: { api_key: "secret-value", provider: "deepseek" },
        retry: 0,
      }),
    )
    expect(get).toHaveBeenCalledWith("/api/personal/settings/models/deepseek", {})
    expect(result.cached).toBe(true)
  })

  it.each([400, 422, 429, 503])(
    "maps settings status %s to a sanitized error without retry",
    async (status) => {
      const get = vi.fn(() =>
        Promise.resolve(new Response("provider /private/path secret", { status })),
      )
      const http: KyHttpClient = {
        delete: vi.fn(),
        get,
        patch: vi.fn(),
        post: vi.fn(),
      }
      const api = createSettingsApi(new ApiClient(fetch, http))

      const error = await api.load().catch((caught: unknown) => caught)

      expect(error).toBeInstanceOf(ApiError)
      expect((error as ApiError).message).not.toContain("provider")
      expect(get).toHaveBeenCalledOnce()
    },
  )
})

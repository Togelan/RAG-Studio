import { describe, expect, it, vi } from "vitest"

import { ApiClient, type KyHttpClient } from "../../api/client"
import { ApiContractError } from "../../api/errors"
import {
  createPublicationGateway,
  PublicationProjectionSchema,
  parseExactOrigin,
} from "./publication-api"

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), { headers: { "Content-Type": "application/json" } })
}

const projection = {
  publication_id: "00000000-0000-4000-8000-000000000020",
  public_key: "00000000-0000-4000-8000-000000000021",
  allowed_origin: "https://widget.example.test",
  state: "enabled",
  key_version: 1,
  audit_event_count: 1,
} as const

describe("publication API contract", () => {
  it("parses and canonicalizes only one exact HTTP origin", () => {
    expect(parseExactOrigin("HTTPS://Widget.Example.TEST:443")).toEqual({
      ok: true,
      origin: "https://widget.example.test",
    })
  })

  it.each(["", "*", "https://example.test/path", "https://example.test?scope=private"])(
    "rejects non-origin input %s before transport",
    (value) => expect(parseExactOrigin(value)).toEqual({ ok: false }),
  )

  it("uses the Personal Lab lifecycle endpoints with CSRF", async () => {
    const response = () => Promise.resolve(jsonResponse(projection))
    const http: KyHttpClient = {
      delete: vi.fn(response),
      get: vi.fn(response),
      patch: vi.fn(),
      post: vi.fn(response),
      put: vi.fn(response),
    }
    const gateway = createPublicationGateway(new ApiClient(fetch, http, () => "csrf-proof"))

    await gateway.load()
    await gateway.publish("https://widget.example.test")
    await gateway.disable()
    await gateway.revoke()

    expect(http.get).toHaveBeenCalledWith("/api/personal/widget-publication", {})
    expect(http.put).toHaveBeenCalledWith(
      "/api/personal/widget-publication",
      expect.objectContaining({
        headers: { "X-CSRF-Token": "csrf-proof" },
        json: { allowed_origin: "https://widget.example.test" },
      }),
    )
    expect(http.post).toHaveBeenCalledWith(
      "/api/personal/widget-publication/disable",
      expect.objectContaining({ headers: { "X-CSRF-Token": "csrf-proof" } }),
    )
    expect(http.delete).toHaveBeenCalledWith(
      "/api/personal/widget-publication",
      expect.objectContaining({ headers: { "X-CSRF-Token": "csrf-proof" } }),
    )
  })

  it.each([
    { ...projection, personal_lab_id: "00000000-0000-4000-8000-000000000099" },
    { ...projection, provider_secret: "secret" },
    { ...projection, state: "unknown" },
    { ...projection, allowed_origin: "*" },
  ])("rejects privileged or malformed BFF projections", async (value) => {
    expect(PublicationProjectionSchema.safeParse(value).success).toBe(false)
    const http: KyHttpClient = {
      delete: vi.fn(),
      get: vi.fn(() => Promise.resolve(jsonResponse(value))),
      patch: vi.fn(),
      post: vi.fn(),
    }

    await expect(
      createPublicationGateway(new ApiClient(fetch, http)).load(),
    ).rejects.toBeInstanceOf(ApiContractError)
  })
})

import { describe, expect, it, vi } from "vitest"

import { ApiClient, type KyHttpClient } from "../../api/client"
import { ApiContractError } from "../../api/errors"
import { BillingProjectionSchema, createBillingGateway } from "./billing-api"

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), { headers: { "Content-Type": "application/json" } })
}

const projection = {
  plan: { amount_usd_cents: 1_000, currency: "USD", interval: "month" },
  status: "none",
  pending: false,
  entitled: false,
  can_manage: false,
} as const

describe("billing API contract", () => {
  it("loads only the display-safe server projection", async () => {
    const get = vi.fn(() => Promise.resolve(jsonResponse(projection)))
    const http: KyHttpClient = { delete: vi.fn(), get, patch: vi.fn(), post: vi.fn() }

    const result = await createBillingGateway(new ApiClient(fetch, http)).load()

    expect(result).toEqual(projection)
    expect(get).toHaveBeenCalledWith("/api/personal/billing", {})
  })

  it("uses CSRF-protected POSTs for hosted Checkout and Portal destinations", async () => {
    const post = vi.fn(() =>
      Promise.resolve(jsonResponse({ url: "https://billing.example.test/hosted" })),
    )
    const http: KyHttpClient = { delete: vi.fn(), get: vi.fn(), patch: vi.fn(), post }
    const gateway = createBillingGateway(new ApiClient(fetch, http, () => "csrf-proof"))

    await gateway.checkout()
    await gateway.portal()

    expect(post).toHaveBeenNthCalledWith(
      1,
      "/api/personal/billing/checkout",
      expect.objectContaining({
        headers: { "X-CSRF-Token": "csrf-proof" },
        json: {},
        retry: 0,
      }),
    )
    expect(post).toHaveBeenNthCalledWith(
      2,
      "/api/personal/billing/portal",
      expect.objectContaining({
        headers: { "X-CSRF-Token": "csrf-proof" },
        json: {},
        retry: 0,
      }),
    )
  })

  it.each([
    { ...projection, stripe_price_id: "price_hidden" },
    { ...projection, status: "paid" },
    { ...projection, plan: { ...projection.plan, amount_usd_cents: -1 } },
    { ...projection, pending: true },
  ])("rejects malformed or privileged projection data", (value) => {
    expect(BillingProjectionSchema.safeParse(value).success).toBe(false)
  })

  it("rejects a non-HTTPS hosted destination", async () => {
    const post = vi.fn(() => Promise.resolve(jsonResponse({ url: "http://billing.test/session" })))
    const http: KyHttpClient = { delete: vi.fn(), get: vi.fn(), patch: vi.fn(), post }

    const error = await createBillingGateway(new ApiClient(fetch, http, () => "proof"))
      .checkout()
      .catch((caught: unknown) => caught)

    expect(error).toBeInstanceOf(ApiContractError)
  })
})

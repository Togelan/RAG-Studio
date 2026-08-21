import { afterEach, describe, expect, it, vi } from "vitest"

import { browserCsrfToken, csrfHeadersForMutation } from "./csrf"
import { ApiError } from "./errors"

describe("browserCsrfToken", () => {
  afterEach(() => vi.unstubAllGlobals())

  it("returns the production proof when production and development proofs exist", () => {
    // Given: a browser with both recognized CSRF cookies and session-looking values.
    vi.stubGlobal("document", {
      cookie:
        "ragstudio-development-session=development-session; ragstudio-development-csrf=development-proof; __Host-ragstudio-session=production-session; __Host-ragstudio-csrf=production-proof",
    })

    // When: a protected request reads its CSRF proof.
    const token = browserCsrfToken()

    // Then: production wins and neither session value can be used as a proof.
    expect(token).toBe("production-proof")
  })

  it("returns the local HTTP development proof when production proof is absent", () => {
    // Given: an explicit local-development cookie pair with no production CSRF cookie.
    vi.stubGlobal("document", {
      cookie:
        "ragstudio-development-session=development-session; ragstudio-development-csrf=local-proof",
    })

    // When: a protected request reads its CSRF proof.
    const token = browserCsrfToken()

    // Then: it sends the readable development CSRF proof, never the session value.
    expect(token).toBe("local-proof")
  })

  it("fails closed when establishment returns no readable proof", async () => {
    const establish = vi.fn(() => Promise.resolve(new Response(null, { status: 204 })))
    const readToken = vi.fn<() => string | null>(() => null)

    const headers = csrfHeadersForMutation("/api/saas/auth/signin", {
      establish,
      readToken,
    })

    await expect(headers).rejects.toMatchObject(
      new ApiError(403, "The request could not be completed. Please try again.", null),
    )
    expect(establish).toHaveBeenCalledOnce()
    expect(readToken).toHaveBeenCalledTimes(2)
  })
})

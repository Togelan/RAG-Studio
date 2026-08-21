import { describe, expect, it } from "vitest"

import type { KyHttpClient, KyRequestOptions } from "../../../api/client"
import { ApiClient } from "../../../api/client"
import { createAuthGateway } from "./auth-api"

type RequestRecord = {
  readonly input: string
  readonly options: KyRequestOptions
}

function responseFor(input: string): Response {
  if (input.endsWith("/csrf") || input.endsWith("/signout")) {
    return new Response(null, { status: 204 })
  }
  if (input.endsWith("/signup")) {
    return new Response('{"confirmation_required":false}', { status: 201 })
  }
  return new Response(
    '{"user_id":"00000000-0000-4000-8000-000000000001","email":"owner@example.test","accounts":[],"active_account_id":null,"workspace":{"id":"00000000-0000-4000-8000-000000000010","name":"Workspace","role":"owner"}}',
  )
}

describe("SaaS authentication gateway", () => {
  it("maps the recoverable BFF lifecycle without returning browser credentials", async () => {
    // Given: a typed relative-path client and the BFF authentication contract.
    const requests: RequestRecord[] = []
    const request = (input: string, options: KyRequestOptions): Promise<Response> => {
      requests.push({ input, options })
      return Promise.resolve(responseFor(input))
    }
    const http: KyHttpClient = {
      delete: request,
      get: request,
      patch: request,
      post: request,
      put: request,
    }
    const gateway = createAuthGateway(new ApiClient(fetch, http, () => "csrf-proof"))

    // When: the UI performs each authentication and workspace-selection transition.
    const signup = await gateway.signUp({
      email: "owner@example.test",
      password: "correct-horse",
    })
    const signin = await gateway.signIn({
      email: "owner@example.test",
      password: "correct-horse",
    })
    await gateway.getSession()
    await gateway.refresh()
    const selected = await gateway.selectWorkspace("00000000-0000-4000-8000-000000000010")
    await gateway.signOut()

    // Then: endpoint order and public models match the BFF without token fields.
    expect(requests.map(({ input }) => input)).toEqual([
      "/api/saas/auth/signup",
      "/api/saas/auth/signin",
      "/api/saas/auth/session",
      "/api/saas/auth/refresh",
      "/api/saas/auth/workspace",
      "/api/saas/auth/signout",
    ])
    expect(signup).toEqual({ confirmation_required: false })
    expect(signin.workspace?.role).toBe("owner")
    expect(selected.workspace?.id).toBe("00000000-0000-4000-8000-000000000010")
    expect(JSON.stringify({ signup, signin, selected })).not.toMatch(
      /access_token|refresh_token|csrf-proof/iu,
    )
  })
})

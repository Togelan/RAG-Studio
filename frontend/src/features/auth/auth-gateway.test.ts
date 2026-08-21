import { HttpResponse, http } from "msw"
import { setupServer } from "msw/node"
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest"

import { ApiClient, type KyHttpClient, type KyRequestOptions } from "../../api/client"
import { AccountIdSchema, WorkspaceIdSchema } from "../account/account-contracts"
import { createAuthGateway } from "./auth-gateway"

const API_ORIGIN = "http://rag-studio.test"
const server = setupServer()

function mswHttpClient(): KyHttpClient {
  const request =
    (method: string) =>
    async (input: string, options: KyRequestOptions): Promise<Response> => {
      const headers = new Headers(options.headers)
      const body = options.json === undefined ? options.body : JSON.stringify(options.json)
      if (options.json !== undefined) headers.set("Content-Type", "application/json")
      return fetch(`${API_ORIGIN}${input}`, {
        method,
        headers,
        ...(body === undefined ? {} : { body }),
        ...(options.signal === undefined ? {} : { signal: options.signal }),
      })
    }
  return {
    delete: request("DELETE"),
    get: request("GET"),
    patch: request("PATCH"),
    post: request("POST"),
    put: request("PUT"),
  }
}

const accountA = "00000000-0000-4000-8000-000000000010"
const accountB = "00000000-0000-4000-8000-000000000020"
const workspaceB = "00000000-0000-4000-8000-000000000021"

function sessionBody(): object {
  return {
    user_id: "00000000-0000-4000-8000-000000000001",
    email: "employee@example.test",
    accounts: [
      {
        id: accountA,
        label: "My account",
        status: "active",
        owner: {
          can_manage_billing: true,
          can_view_plan: true,
          can_view_limits: true,
        },
        workspaces: [],
      },
      {
        id: accountB,
        label: "Department",
        status: "active",
        owner: null,
        workspaces: [{ id: workspaceB, name: "Support", role: "member" }],
      },
    ],
    active_account_id: null,
    workspace: null,
  }
}

describe("canonical RAG-Studio authentication gateway", () => {
  beforeAll(() => server.listen({ onUnhandledRequest: "error" }))
  afterEach(() => server.resetHandlers())
  afterAll(() => server.close())

  it("recovers an expired session through refresh without exposing credentials", async () => {
    // Given: the session endpoint rejects once and the HttpOnly refresh session remains valid.
    let sessionRequests = 0
    const observedBodies: string[] = []
    server.use(
      http.get(`${API_ORIGIN}/api/saas/auth/session`, () => {
        sessionRequests += 1
        return sessionRequests === 1
          ? HttpResponse.json({ detail: "provider secret" }, { status: 401 })
          : HttpResponse.json(sessionBody())
      }),
      http.post(`${API_ORIGIN}/api/saas/auth/refresh`, async ({ request }) => {
        observedBodies.push(await request.text())
        return HttpResponse.json(sessionBody())
      }),
    )
    const gateway = createAuthGateway(new ApiClient(fetch, mswHttpClient(), () => "csrf-proof"))

    // When: the application recovers the browser session.
    const session = await gateway.recover()

    // Then: refresh is cookie/CSRF based and no provider token enters the public model.
    expect(session.accounts).toHaveLength(2)
    expect(observedBodies).toEqual(["{}"])
    expect(JSON.stringify(session)).not.toMatch(/access_token|refresh_token|provider secret/iu)
  })

  it("restores the CSRF companion cookie after a valid session recovery", async () => {
    // Given: a valid long-lived BFF session but no readable CSRF companion cookie.
    let csrfRequests = 0
    server.use(
      http.get(`${API_ORIGIN}/api/saas/auth/session`, () => HttpResponse.json(sessionBody())),
      http.get(`${API_ORIGIN}/api/saas/auth/csrf`, () => {
        csrfRequests += 1
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const gateway = createAuthGateway(new ApiClient(fetch, mswHttpClient(), () => null))

    // When: the application recovers the BFF session on a new page load.
    const session = await gateway.recover()

    // Then: the browser receives fresh CSRF state before any Personal Lab mutation.
    expect(session.user_id).toBe("00000000-0000-4000-8000-000000000001")
    expect(csrfRequests).toBe(1)
  })

  it("keeps multiple accounts unselected and projects a foreign member role", async () => {
    // Given: one owned Account and one foreign Account where the user is only a Workspace member.
    server.use(
      http.get(`${API_ORIGIN}/api/saas/auth/session`, () => HttpResponse.json(sessionBody())),
    )
    const gateway = createAuthGateway(new ApiClient(fetch, mswHttpClient(), () => "csrf-proof"))

    // When: the session is loaded without an explicit Account selection.
    const session = await gateway.getSession()

    // Then: no first Account is guessed and foreign ownership is not projected.
    expect(session.active_account_id).toBeNull()
    expect(session.accounts[1]?.owner).toBeNull()
    expect(session.accounts[1]?.workspaces[0]?.role).toBe("member")
  })

  it("selects Account and Workspace explicitly with CSRF and parses a 204 signout", async () => {
    // Given: a server-confirmed foreign Workspace and a signout endpoint with no body.
    const observed: Array<{ readonly csrf: string | null; readonly body: unknown }> = []
    server.use(
      http.put(`${API_ORIGIN}/api/saas/auth/context`, async ({ request }) => {
        observed.push({
          csrf: request.headers.get("X-CSRF-Token"),
          body: await request.json(),
        })
        return HttpResponse.json({
          ...sessionBody(),
          active_account_id: accountB,
          workspace: { id: workspaceB, name: "Support", role: "member" },
        })
      }),
      http.post(
        `${API_ORIGIN}/api/saas/auth/signout`,
        () => new HttpResponse(null, { status: 204 }),
      ),
    )
    const gateway = createAuthGateway(new ApiClient(fetch, mswHttpClient(), () => "csrf-proof"))

    // When: the user explicitly selects the foreign context, then signs out.
    const selected = await gateway.selectContext(
      AccountIdSchema.parse(accountB),
      WorkspaceIdSchema.parse(workspaceB),
    )
    await gateway.signOut()

    // Then: only typed identifiers and the double-submit proof reach the BFF.
    expect(selected.workspace?.role).toBe("member")
    expect(observed).toEqual([
      { csrf: "csrf-proof", body: { account_id: accountB, workspace_id: workspaceB } },
    ])
  })

  it("rejects malformed session responses with a sanitized contract error", async () => {
    // Given: a response containing a role outside the trusted contract.
    server.use(
      http.get(`${API_ORIGIN}/api/saas/auth/session`, () =>
        HttpResponse.json({ ...sessionBody(), workspace: { id: workspaceB, role: "superuser" } }),
      ),
    )
    const gateway = createAuthGateway(new ApiClient(fetch, mswHttpClient(), () => "csrf-proof"))

    // When: the boundary parses the untrusted response.
    const outcome = gateway.getSession()

    // Then: raw response details are replaced with the stable client message.
    await expect(outcome).rejects.toThrow("The request could not be completed")
  })
})

import { afterEach, describe, expect, it, vi } from "vitest"

import { ApiError } from "../../api/errors"
import type { AuthGateway, AuthSession } from "../auth/auth-gateway"
import { ACTIVE_SESSION_STORAGE_KEY } from "../chat/model"
import { AccountContextController } from "./account-context"
import { AccountIdSchema, UserIdSchema, WorkspaceIdSchema } from "./account-contracts"

const accountId = AccountIdSchema.parse("00000000-0000-4000-8000-000000000010")
const workspaceA = WorkspaceIdSchema.parse("00000000-0000-4000-8000-000000000011")
const workspaceB = WorkspaceIdSchema.parse("00000000-0000-4000-8000-000000000012")

afterEach(() => globalThis.localStorage.removeItem(ACTIVE_SESSION_STORAGE_KEY))

function session(workspaceId = workspaceA): AuthSession {
  return {
    user_id: UserIdSchema.parse("00000000-0000-4000-8000-000000000001"),
    email: "owner@example.test",
    accounts: [],
    active_account_id: accountId,
    workspace: { id: workspaceId, name: "Workspace", role: "owner" },
  }
}

function gatewayWith(
  selectContext: AuthGateway["selectContext"],
  getSession: AuthGateway["getSession"] = () => Promise.resolve(session()),
): AuthGateway {
  return {
    getSession,
    recover: getSession,
    refresh: getSession,
    selectContext,
    signIn: () => Promise.resolve(session()),
    signOut: () => Promise.resolve(),
    signUp: () => Promise.resolve({ confirmation_required: false }),
  }
}

describe("Account context controller", () => {
  it("clears the remembered Personal Chat session only after successful sign-out", async () => {
    // Given: a ready account with a remembered Personal Chat session.
    globalThis.localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, "personal-session-a")
    const controller = new AccountContextController(
      gatewayWith(() => Promise.resolve(session())),
      session(),
    )

    // When: server-side sign-out succeeds.
    await controller.signOut()

    // Then: the account is unauthenticated and the prior chat cannot be restored.
    expect(controller.state).toEqual({ kind: "unauthenticated" })
    expect(globalThis.localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY)).toBeNull()
  })

  it("preserves the remembered Personal Chat session when sign-out fails", async () => {
    // Given: a ready account whose server-side sign-out will fail.
    globalThis.localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, "personal-session-a")
    const gateway: AuthGateway = {
      ...gatewayWith(() => Promise.resolve(session())),
      signOut: () =>
        Promise.reject(new ApiError(503, "The service is temporarily unavailable.", null)),
    }
    const controller = new AccountContextController(gateway, session())

    // When: sign-out is rejected.
    await controller.signOut()

    // Then: the stale-state cleanup is not mistaken for a completed sign-out.
    expect(controller.state).toEqual({
      kind: "error",
      message: "The service is temporarily unavailable.",
    })
    expect(globalThis.localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY)).toBe("personal-session-a")
  })

  it("clears protected context immediately and aborts a stale rapid switch", async () => {
    // Given: two context selections where only the second request resolves.
    const signals: AbortSignal[] = []
    const selectContext = vi.fn<AuthGateway["selectContext"]>((_account, workspace, options) => {
      if (options?.signal !== undefined) signals.push(options.signal)
      if (workspace === workspaceB) return Promise.resolve(session(workspaceB))
      return new Promise<AuthSession>(() => undefined)
    })
    const controller = new AccountContextController(gatewayWith(selectContext), session())

    // When: a second selection supersedes the first before it finishes.
    void controller.select(accountId, workspaceA)
    expect(controller.state).toEqual({ kind: "selection-pending" })
    await controller.select(accountId, workspaceB)

    // Then: the stale request is aborted and only the confirmed second context is retained.
    expect(signals[0]?.aborted).toBe(true)
    expect(controller.state).toEqual({ kind: "ready", session: session(workspaceB) })
  })

  it("clears sensitive context on a revoked selection denial", async () => {
    // Given: a previously ready Workspace whose membership has been revoked.
    const denied = new ApiError(403, "The request could not be completed. Please try again.", null)
    const controller = new AccountContextController(
      gatewayWith(() => Promise.reject(denied)),
      session(),
    )

    // When: the user attempts to select the revoked context.
    await controller.select(accountId, workspaceA)

    // Then: no prior Account, Workspace, role, or server detail remains in state.
    expect(controller.state).toEqual({ kind: "forbidden" })
    expect(JSON.stringify(controller.state)).not.toMatch(/workspace|owner|provider/iu)
  })

  it("maps unauthorized recovery to an empty unauthenticated state", async () => {
    // Given: the browser cookie no longer resolves to a valid session.
    const rejected = new ApiError(
      401,
      "The request could not be completed. Please try again.",
      null,
    )
    const controller = new AccountContextController(
      gatewayWith(
        () => Promise.resolve(session()),
        () => Promise.reject(rejected),
      ),
      session(),
    )

    // When: session recovery runs.
    await controller.recover()

    // Then: the prior context is cleared and the raw denial is not retained.
    expect(controller.state).toEqual({ kind: "unauthenticated" })
  })

  it("removes listeners and aborts in-flight work when disposed", async () => {
    // Given: an observed controller with a recover request that remains in flight.
    const signalSeen = vi.fn<(signal: AbortSignal) => void>()
    const gateway = gatewayWith(
      () => Promise.resolve(session()),
      (options) => {
        if (options?.signal !== undefined) signalSeen(options.signal)
        return new Promise<AuthSession>(() => undefined)
      },
    )
    const controller = new AccountContextController(gateway)
    const listener = vi.fn()
    controller.subscribe(listener)
    void controller.recover()

    // When: the owning surface disposes the controller.
    controller.dispose()

    // Then: the request is aborted and no later state can reach the detached listener.
    expect(signalSeen.mock.calls[0]?.[0].aborted).toBe(true)
    expect(listener).toHaveBeenCalledTimes(1)
  })
})

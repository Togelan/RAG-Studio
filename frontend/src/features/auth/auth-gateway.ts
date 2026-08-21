import { z } from "zod"

import { type ApiClient, apiClient, type JsonRequestOptions } from "../../api/client"
import { ApiError } from "../../api/errors"
import type { AccountId, WorkspaceId } from "../account/account-contracts"
import {
  type AuthSession,
  AuthSessionSchema,
  type Credentials,
  CredentialsSchema,
  type SignupOutcome,
  SignupOutcomeSchema,
} from "./auth-contracts"

export type AuthGateway = {
  readonly getSession: (options?: JsonRequestOptions) => Promise<AuthSession>
  readonly recover: (options?: JsonRequestOptions) => Promise<AuthSession>
  readonly refresh: (options?: JsonRequestOptions) => Promise<AuthSession>
  readonly selectContext: (
    accountId: AccountId,
    workspaceId: WorkspaceId | null,
    options?: JsonRequestOptions,
  ) => Promise<AuthSession>
  readonly signIn: (credentials: Credentials, options?: JsonRequestOptions) => Promise<AuthSession>
  readonly signOut: (options?: JsonRequestOptions) => Promise<void>
  readonly signUp: (
    credentials: Credentials,
    options?: JsonRequestOptions,
  ) => Promise<SignupOutcome>
}

export function createAuthGateway(client: ApiClient = apiClient): AuthGateway {
  const getSession = (options?: JsonRequestOptions): Promise<AuthSession> =>
    client.get("/api/saas/auth/session", AuthSessionSchema, options)
  const establishCsrf = (options?: JsonRequestOptions): Promise<void> =>
    client.get("/api/saas/auth/csrf", z.undefined(), options)
  const refresh = (options?: JsonRequestOptions): Promise<AuthSession> =>
    client.post("/api/saas/auth/refresh", {}, AuthSessionSchema, options)

  return {
    getSession,
    recover: async (options) => {
      try {
        const session = await getSession(options)
        await establishCsrf(options)
        return session
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          return refresh(options)
        }
        throw error
      }
    },
    refresh,
    selectContext: (accountId, workspaceId, options) =>
      client.put(
        "/api/saas/auth/context",
        { account_id: accountId, workspace_id: workspaceId },
        AuthSessionSchema,
        options,
      ),
    signIn: (credentials, options) =>
      client.post(
        "/api/saas/auth/signin",
        CredentialsSchema.parse(credentials),
        AuthSessionSchema,
        options,
      ),
    signOut: (options) => client.post("/api/saas/auth/signout", {}, z.undefined(), options),
    signUp: (credentials, options) =>
      client.post(
        "/api/saas/auth/signup",
        CredentialsSchema.parse(credentials),
        SignupOutcomeSchema,
        options,
      ),
  }
}

export type { AuthSession, Credentials, SignupOutcome }

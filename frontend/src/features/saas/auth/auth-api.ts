import { z } from "zod"

import { type ApiClient, apiClient } from "../../../api/client"
import { WorkspaceIdSchema } from "../../account/account-contracts"
import {
  AuthSessionSchema as CanonicalAuthSessionSchema,
  type SignupOutcome,
  SignupOutcomeSchema,
} from "../../auth/auth-contracts"
import { createAuthGateway as createCanonicalAuthGateway } from "../../auth/auth-gateway"
import type { Credentials } from "../model"

const WorkspaceContextSchema = z.object({
  id: z.string().uuid(),
  name: z.string().min(1).max(120).nullable().optional(),
  role: z.enum(["owner", "admin", "member"]),
})

export const AuthSessionSchema = z.object({
  user_id: z.string().uuid(),
  email: z.string().email(),
  workspace: WorkspaceContextSchema.nullable(),
})

export { SignupOutcomeSchema }
export type AuthSession = z.infer<typeof AuthSessionSchema>
export type { SignupOutcome }

export type AuthGateway = {
  readonly getSession: () => Promise<AuthSession>
  readonly refresh: () => Promise<AuthSession>
  readonly selectWorkspace: (workspaceId: string) => Promise<AuthSession>
  readonly signIn: (credentials: Credentials) => Promise<AuthSession>
  readonly signOut: () => Promise<void>
  readonly signUp: (credentials: Credentials) => Promise<SignupOutcome>
}

export function createAuthGateway(client: ApiClient = apiClient): AuthGateway {
  const canonical = createCanonicalAuthGateway(client)
  return {
    getSession: canonical.getSession,
    refresh: canonical.refresh,
    selectWorkspace: (workspaceId) =>
      client.put(
        "/api/saas/auth/workspace",
        { workspace_id: WorkspaceIdSchema.parse(workspaceId) },
        CanonicalAuthSessionSchema,
      ),
    signIn: canonical.signIn,
    signOut: canonical.signOut,
    signUp: canonical.signUp,
  }
}

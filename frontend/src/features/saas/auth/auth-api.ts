import { z } from "zod"

import { type ApiClient, apiClient } from "../../../api/client"
import type { Credentials } from "../model"

const WorkspaceContextSchema = z.object({
  id: z.string().uuid(),
  role: z.enum(["owner", "admin", "member"]),
})

export const AuthSessionSchema = z.object({
  user_id: z.string().uuid(),
  email: z.string().email(),
  workspace: WorkspaceContextSchema.nullable(),
})

export const SignupOutcomeSchema = z.object({
  confirmation_required: z.boolean(),
})

export type AuthSession = z.infer<typeof AuthSessionSchema>
export type SignupOutcome = z.infer<typeof SignupOutcomeSchema>

export interface AuthGateway {
  getSession(): Promise<AuthSession>
  refresh(): Promise<AuthSession>
  selectWorkspace(workspaceId: string): Promise<AuthSession>
  signIn(credentials: Credentials): Promise<AuthSession>
  signOut(): Promise<void>
  signUp(credentials: Credentials): Promise<SignupOutcome>
}

export function createAuthGateway(client: ApiClient = apiClient): AuthGateway {
  return {
    getSession: () => client.get("/api/saas/auth/session", AuthSessionSchema),
    refresh: () => client.post("/api/saas/auth/refresh", {}, AuthSessionSchema),
    selectWorkspace: (workspaceId) =>
      client.put("/api/saas/auth/workspace", { workspace_id: workspaceId }, AuthSessionSchema),
    signIn: (credentials) => client.post("/api/saas/auth/signin", credentials, AuthSessionSchema),
    signOut: () => client.post("/api/saas/auth/signout", {}, z.undefined()),
    signUp: (credentials) => client.post("/api/saas/auth/signup", credentials, SignupOutcomeSchema),
  }
}

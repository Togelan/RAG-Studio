import { z } from "zod"

import { type ApiClient, apiClient } from "../../../api/client"
import { type WorkspaceRole, workspaceRoles } from "../model"

export const invitationRoles = ["admin", "member"] as const
export type InvitationRole = (typeof invitationRoles)[number]

const MembershipSchema = z.object({
  user_id: z.string().uuid(),
  role: z.enum(workspaceRoles),
})

const InvitationSchema = z.object({
  id: z.string().uuid(),
  email: z.string().email(),
  role: z.enum(invitationRoles),
  status: z.string(),
  expires_at: z.string().datetime().nullable(),
})

export type Membership = z.infer<typeof MembershipSchema>
export type Invitation = z.infer<typeof InvitationSchema>
export type InvitationInput = { readonly email: string; readonly role: InvitationRole }

export type PeopleGateway = {
  readonly listMembers: (workspaceId: string) => Promise<readonly Membership[]>
  readonly changeMembership: (
    workspaceId: string,
    userId: string,
    role: InvitationRole,
  ) => Promise<Membership>
  readonly revokeMembership: (workspaceId: string, userId: string) => Promise<void>
  readonly listInvitations: (workspaceId: string) => Promise<readonly Invitation[]>
  readonly createInvitation: (workspaceId: string, input: InvitationInput) => Promise<Invitation>
  readonly revokeInvitation: (workspaceId: string, invitationId: string) => Promise<void>
}

function workspacePath(workspaceId: string): string {
  return `/api/saas/workspaces/${encodeURIComponent(workspaceId)}`
}

export function createPeopleGateway(client: ApiClient = apiClient): PeopleGateway {
  return {
    listMembers: (workspaceId) =>
      client.get(`${workspacePath(workspaceId)}/members`, z.array(MembershipSchema)),
    changeMembership: (workspaceId, userId, role) =>
      client.patch(
        `${workspacePath(workspaceId)}/members/${encodeURIComponent(userId)}`,
        { role },
        MembershipSchema,
      ),
    revokeMembership: (workspaceId, userId) =>
      client.delete(
        `${workspacePath(workspaceId)}/members/${encodeURIComponent(userId)}`,
        z.undefined(),
      ),
    listInvitations: (workspaceId) =>
      client.get(`${workspacePath(workspaceId)}/invitations`, z.array(InvitationSchema)),
    createInvitation: (workspaceId, input) =>
      client.post(`${workspacePath(workspaceId)}/invitations`, input, InvitationSchema, {
        headers: { "Idempotency-Key": `invitation-${crypto.randomUUID()}` },
      }),
    revokeInvitation: (workspaceId, invitationId) =>
      client.delete(
        `${workspacePath(workspaceId)}/invitations/${encodeURIComponent(invitationId)}`,
        z.undefined(),
      ),
  }
}

export function canManageInvitations(role: WorkspaceRole): boolean {
  return role === "owner" || role === "admin"
}

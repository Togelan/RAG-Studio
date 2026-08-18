import { z } from "zod"

import { type ApiClient, apiClient } from "../../../api/client"
import { type WorkspaceSummaryResponse, WorkspaceSummarySchema } from "../workspaces/workspace-api"

const MembershipSchema = z.object({
  user_id: z.string().uuid(),
  role: z.enum(["owner", "admin", "member"]),
})

export type WorkspaceLifecycleMember = z.infer<typeof MembershipSchema>

export type WorkspaceLifecycleGateway = {
  readonly acceptInvitation: (token: string) => Promise<WorkspaceSummaryResponse>
  readonly archiveWorkspace: (workspaceId: string) => Promise<void>
  readonly listMembers: (workspaceId: string) => Promise<readonly WorkspaceLifecycleMember[]>
  readonly transferOwnership: (workspaceId: string, targetUserId: string) => Promise<void>
}

function workspacePath(workspaceId: string): string {
  return `/api/saas/workspaces/${encodeURIComponent(workspaceId)}`
}

export function createWorkspaceLifecycleGateway(
  client: ApiClient = apiClient,
): WorkspaceLifecycleGateway {
  return {
    acceptInvitation: (token) =>
      client.post("/api/saas/workspace-invitations/accept", { token }, WorkspaceSummarySchema),
    archiveWorkspace: (workspaceId) =>
      client.post(`${workspacePath(workspaceId)}/archive`, {}, z.undefined()),
    listMembers: (workspaceId) =>
      client.get(`${workspacePath(workspaceId)}/members`, z.array(MembershipSchema)),
    transferOwnership: (workspaceId, targetUserId) =>
      client.post(
        `${workspacePath(workspaceId)}/transfer`,
        { target_user_id: targetUserId },
        z.undefined(),
      ),
  }
}

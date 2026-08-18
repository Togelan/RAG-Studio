import { z } from "zod"

import { type ApiClient, apiClient } from "../../../api/client"

export const WorkspaceSummarySchema = z.object({
  id: z.string().uuid(),
  name: z.string().min(1).max(120),
  role: z.enum(["owner", "admin", "member"]),
})

export const WorkspaceListSchema = z.array(WorkspaceSummarySchema)
export type WorkspaceSummaryResponse = z.infer<typeof WorkspaceSummarySchema>

export interface WorkspaceGateway {
  create(name: string): Promise<WorkspaceSummaryResponse>
  list(): Promise<readonly WorkspaceSummaryResponse[]>
}

export function createWorkspaceGateway(client: ApiClient = apiClient): WorkspaceGateway {
  return {
    create: (name) =>
      client.post("/api/saas/workspaces", { name }, WorkspaceSummarySchema, {
        headers: { "Idempotency-Key": `workspace-${crypto.randomUUID()}` },
      }),
    list: () => client.get("/api/saas/workspaces", WorkspaceListSchema),
  }
}

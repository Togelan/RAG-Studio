import { z } from "zod"

import { type ApiClient, apiClient } from "../../../api/client"
import { createWorkspaceGateway as createCanonicalWorkspaceGateway } from "../../account/workspace-gateway"

export const WorkspaceSummarySchema = z.object({
  id: z.string().uuid(),
  name: z.string().min(1).max(120),
  role: z.enum(["owner", "admin", "member"]),
})

export const WorkspaceListSchema = z.array(WorkspaceSummarySchema)
export type WorkspaceSummaryResponse = z.infer<typeof WorkspaceSummarySchema>

export type WorkspaceGateway = {
  readonly create: (name: string) => Promise<WorkspaceSummaryResponse>
  readonly list: () => Promise<readonly WorkspaceSummaryResponse[]>
}

export function createWorkspaceGateway(client: ApiClient = apiClient): WorkspaceGateway {
  const canonical = createCanonicalWorkspaceGateway(client)
  return {
    create: (name) => canonical.create(name),
    list: canonical.list,
  }
}

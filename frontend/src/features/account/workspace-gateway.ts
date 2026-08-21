import { z } from "zod"

import { type ApiClient, apiClient, type JsonRequestOptions } from "../../api/client"
import { WorkspaceIdSchema, WorkspaceRoleSchema } from "./account-contracts"

export const WorkspaceSummarySchema = z
  .object({
    id: WorkspaceIdSchema,
    name: z.string().min(1).max(120),
    role: WorkspaceRoleSchema,
  })
  .strict()
export const WorkspaceListSchema = z.array(WorkspaceSummarySchema).readonly()
export type WorkspaceSummary = z.infer<typeof WorkspaceSummarySchema>

export type WorkspaceGateway = {
  readonly create: (name: string, options?: JsonRequestOptions) => Promise<WorkspaceSummary>
  readonly list: (options?: JsonRequestOptions) => Promise<readonly WorkspaceSummary[]>
}

export function createWorkspaceGateway(client: ApiClient = apiClient): WorkspaceGateway {
  return {
    create: (name, options) =>
      client.post("/api/saas/workspaces", { name }, WorkspaceSummarySchema, {
        ...options,
        headers: {
          ...options?.headers,
          "Idempotency-Key": `workspace-${crypto.randomUUID()}`,
        },
      }),
    list: (options) => client.get("/api/saas/workspaces", WorkspaceListSchema, options),
  }
}

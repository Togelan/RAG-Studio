import { z } from "zod"

import { type ApiClient, apiClient } from "../../../api/client"

const SourceDocumentSchema = z.object({
  chunk_count: z.number().int().nonnegative(),
  created_at: z.string(),
  doc_id: z.string().min(1),
  filename: z.string().min(1).max(255),
})

const SourceListSchema = z.object({
  documents: z.array(SourceDocumentSchema),
  next_cursor: z.string().nullable(),
  truncated: z.boolean(),
})

const SourceUploadSchema = z.object({
  chunk_count: z.number().int().positive(),
  doc_id: z.string().min(1),
})

export type SourceDocument = z.infer<typeof SourceDocumentSchema>

export type SourcesGateway = {
  readonly list: (workspaceId: string) => Promise<readonly SourceDocument[]>
  readonly remove: (workspaceId: string, documentId: string) => Promise<void>
  readonly upload: (workspaceId: string, file: File) => Promise<void>
}

function documentsPath(workspaceId: string): string {
  return `/api/saas/workspaces/${encodeURIComponent(workspaceId)}/documents`
}

export function createSourcesGateway(client: ApiClient = apiClient): SourcesGateway {
  return {
    list: async (workspaceId) =>
      (await client.get(documentsPath(workspaceId), SourceListSchema)).documents,
    remove: (workspaceId, documentId) =>
      client
        .delete(
          `${documentsPath(workspaceId)}/${encodeURIComponent(documentId)}`,
          z.object({ deleted_count: z.number().int().nonnegative() }),
        )
        .then(() => undefined),
    upload: (workspaceId, file) => {
      const body = new FormData()
      body.set("file", file)
      return client
        .postForm(`${documentsPath(workspaceId)}/upload`, body, SourceUploadSchema)
        .then(() => undefined)
    },
  }
}

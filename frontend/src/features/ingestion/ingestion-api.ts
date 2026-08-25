import { ApiClient } from "../../api/client"
import { ApiContractError, apiErrorFromResponse } from "../../api/errors"
import {
  type ChunksPage,
  ChunksPageSchema,
  type DeleteResponse,
  DeleteResponseSchema,
  type DocumentRecord,
  type DocumentsPage,
  DocumentsPageSchema,
  DuplicateResponseSchema,
  type IngestionProgress,
  ProgressResponseSchema,
  type ReingestResponse,
  ReingestResponseSchema,
  UploadResponseSchema,
  type UploadResult,
} from "./ingestion-schemas"

export type UploadAction = "cancel" | "default" | "rename" | "replace"
export type UploadTransport = (
  path: string,
  body: FormData,
  signal?: AbortSignal,
) => Promise<Response>

export type IngestionApi = {
  readonly chunks: (docId: string, cursor?: string, signal?: AbortSignal) => Promise<ChunksPage>
  readonly clear: (signal?: AbortSignal) => Promise<DeleteResponse>
  readonly deleteDocument: (docId: string, signal?: AbortSignal) => Promise<DeleteResponse>
  readonly documents: (cursor?: string, signal?: AbortSignal) => Promise<DocumentsPage>
  readonly progress: (fileId: string, signal?: AbortSignal) => Promise<IngestionProgress>
  readonly reingest: (
    document: Pick<DocumentRecord, "doc_id" | "filename">,
    signal?: AbortSignal,
  ) => Promise<ReingestResponse>
  readonly upload: (
    file: File,
    action?: UploadAction,
    signal?: AbortSignal,
  ) => Promise<UploadResult>
}

export type ReingestSummary = {
  readonly failed: number
  readonly skipped: number
  readonly succeeded: number
  readonly total: number
}

export function bindBrowserFetch(
  fetchImplementation: typeof fetch = globalThis.fetch,
): typeof fetch {
  return fetchImplementation.bind(globalThis)
}

function createBrowserApiClient(): ApiClient {
  return new ApiClient(bindBrowserFetch())
}

function queryPath(base: string, cursor: string | undefined): string {
  return cursor === undefined ? base : `${base}?cursor=${encodeURIComponent(cursor)}`
}

async function responseJson(response: Response): Promise<unknown> {
  try {
    return JSON.parse(await response.text())
  } catch (error) {
    if (error instanceof SyntaxError) {
      throw new ApiContractError()
    }
    throw error
  }
}

function parseUploadResult(response: Response, value: unknown): UploadResult {
  if (response.status === 409) {
    const duplicate = DuplicateResponseSchema.safeParse(value)
    if (!duplicate.success) {
      throw new ApiContractError()
    }
    return { kind: "duplicate", response: duplicate.data }
  }
  if (!response.ok) {
    throw apiErrorFromResponse(response)
  }
  const upload = UploadResponseSchema.safeParse(value)
  if (!upload.success) {
    throw new ApiContractError()
  }
  return { kind: "accepted", response: upload.data }
}

function options(signal: AbortSignal | undefined): { readonly signal?: AbortSignal } {
  return signal === undefined ? {} : { signal }
}

export function createIngestionApi(
  client: ApiClient = createBrowserApiClient(),
  uploadTransport?: UploadTransport,
): IngestionApi {
  const transport =
    uploadTransport ??
    ((path: string, body: FormData, signal?: AbortSignal) =>
      client.postFormResponse(path, body, options(signal)))
  return {
    documents: (cursor, signal) =>
      client.get(
        queryPath("/api/personal/knowledge/documents", cursor),
        DocumentsPageSchema,
        options(signal),
      ),
    chunks: (docId, cursor, signal) =>
      client.get(
        queryPath(`/api/personal/knowledge/documents/${encodeURIComponent(docId)}/chunks`, cursor),
        ChunksPageSchema,
        options(signal),
      ),
    deleteDocument: (docId, signal) =>
      client.delete(
        `/api/personal/knowledge/documents/${encodeURIComponent(docId)}`,
        DeleteResponseSchema,
        options(signal),
      ),
    clear: (signal) =>
      client.delete("/api/personal/knowledge/clear", DeleteResponseSchema, options(signal)),
    progress: (fileId, signal) =>
      client.get(
        `/api/personal/knowledge/progress/${encodeURIComponent(fileId)}`,
        ProgressResponseSchema,
        options(signal),
      ),
    reingest: (document, signal) =>
      client.post(
        `/api/personal/knowledge/documents/${encodeURIComponent(document.doc_id)}/reindex`,
        {},
        ReingestResponseSchema,
        options(signal),
      ),
    upload: async (file, action = "default", signal) => {
      const body = new FormData()
      body.append("file", file, file.name)
      const suffix = action === "default" ? "" : `?action=${action}`
      const response = await transport(`/api/personal/knowledge/upload${suffix}`, body, signal)
      if (!response.ok && response.status !== 409) throw apiErrorFromResponse(response)
      return parseUploadResult(response, await responseJson(response))
    },
  }
}

export async function reingestSequentially(
  documents: readonly Pick<DocumentRecord, "doc_id" | "filename">[],
  reingest: (document: Pick<DocumentRecord, "doc_id" | "filename">) => Promise<ReingestResponse>,
  onProgress: (completed: number) => void,
): Promise<ReingestSummary> {
  let succeeded = 0
  let skipped = 0
  let failed = 0

  for (const document of documents) {
    try {
      const response = await reingest(document)
      if (response.status === "skipped") {
        skipped += 1
      } else {
        succeeded += 1
      }
    } catch (error) {
      if (!(error instanceof Error)) {
        throw error
      }
      failed += 1
    }
    onProgress(succeeded + skipped + failed)
  }

  return { failed, skipped, succeeded, total: documents.length }
}

export const ingestionApi = createIngestionApi()

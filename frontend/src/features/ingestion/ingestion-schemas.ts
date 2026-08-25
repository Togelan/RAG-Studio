import { z } from "zod"

const LegacyDocumentSchema = z.object({
  doc_id: z.string().min(1),
  filename: z.string().min(1),
  chunks_count: z.number().int().nonnegative(),
  chunk_size: z.number().int().nonnegative(),
  chunk_overlap: z.number().int().nonnegative(),
  created_at: z.string(),
  strategy: z.string().min(1),
  schema_version: z.number().int().positive(),
})

const PersonalDocumentSchema = z
  .object({
    doc_id: z.string().min(1),
    filename: z.string().min(1),
    chunk_count: z.number().int().nonnegative(),
    strategy: z.string().min(1),
  })
  .transform(({ chunk_count, ...document }) => ({ ...document, chunks_count: chunk_count }))

export const DocumentSchema = z.union([LegacyDocumentSchema, PersonalDocumentSchema])
export type DocumentRecord = z.infer<typeof DocumentSchema>

export const DocumentsPageSchema = z
  .object({
    documents: z.array(DocumentSchema),
    total: z.number().int().nonnegative().nullable().optional(),
    next_cursor: z.string().nullable(),
    truncated: z.boolean(),
  })
  .transform(({ total, ...page }) => ({ ...page, total: total ?? null }))
export type DocumentsPage = z.infer<typeof DocumentsPageSchema>

export const ChunkSchema = z.object({
  point_id: z.string().min(1),
  chunk_index: z.number().int().nonnegative(),
  text: z.string(),
  token_count: z.number().int().nonnegative().optional(),
  page: z.number().int().nonnegative().nullable().optional(),
  strategy: z.string().min(1).optional(),
  csv_row: z.number().int().nonnegative().nullable().optional(),
})
export type ChunkRecord = z.infer<typeof ChunkSchema>

export const ChunksPageSchema = z.object({
  chunks: z.array(ChunkSchema),
  next_cursor: z.string().nullable(),
  truncated: z.boolean(),
})
export type ChunksPage = z.infer<typeof ChunksPageSchema>

export const DeleteResponseSchema = z.union([
  z.object({
    status: z.literal("ok"),
    message: z.string(),
    deleted_count: z.number().int().nonnegative(),
  }),
  z.object({ deleted: z.number().int().nonnegative() }).transform(({ deleted }) => ({
    status: "ok" as const,
    message: "",
    deleted_count: deleted,
  })),
])
export type DeleteResponse = z.infer<typeof DeleteResponseSchema>

export const UploadResponseSchema = z.object({
  status: z.enum(["processing", "cancelled", "unchanged"]),
  file_id: z.string(),
  message: z.string(),
})
export type UploadResponse = z.infer<typeof UploadResponseSchema>

export const DuplicateResponseSchema = z.object({
  status: z.literal("duplicate"),
  filename: z.string().min(1),
  existing_chunks: z.number().int().nonnegative(),
  existing_size: z.number().int().nonnegative(),
  stored_chunk_size: z.number().int().nonnegative(),
  stored_chunk_overlap: z.number().int().nonnegative(),
  new_file_size: z.number().int().nonnegative(),
  estimated_chunks: z.number().int().nonnegative(),
  chunks_settings_changed: z.boolean(),
  current_chunk_size: z.number().int().positive(),
  current_chunk_overlap: z.number().int().nonnegative(),
})
export type DuplicateResponse = z.infer<typeof DuplicateResponseSchema>

export const ProgressResponseSchema = z.union([
  z.object({
    file_id: z.string().min(1),
    status: z.enum(["processing", "done", "error"]),
    message: z.string(),
    chunks_count: z.number().int().nonnegative().nullable().optional(),
    error: z.string().nullable().optional(),
  }),
  z
    .object({
      file_id: z.string().min(1),
      status: z.enum(["processing", "complete", "error"]),
      code: z.string().nullable().optional(),
    })
    .transform(({ code, file_id, status }) => ({
      file_id,
      status: status === "complete" ? ("done" as const) : status,
      message: code ?? "",
      error: status === "error" ? code : null,
    })),
])
export type IngestionProgress = z.infer<typeof ProgressResponseSchema>

export const ReingestResponseSchema = z.object({
  status: z.enum(["processing", "skipped"]),
  file_id: z.string().min(1),
  message: z.string(),
  detail: z.string().nullable().optional(),
})
export type ReingestResponse = z.infer<typeof ReingestResponseSchema>

export type UploadResult =
  | { readonly kind: "accepted"; readonly response: UploadResponse }
  | { readonly kind: "duplicate"; readonly response: DuplicateResponse }

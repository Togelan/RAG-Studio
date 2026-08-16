import { z } from "zod"

export const DocumentSchema = z.object({
  doc_id: z.string().min(1),
  filename: z.string().min(1),
  chunks_count: z.number().int().nonnegative(),
  chunk_size: z.number().int().nonnegative(),
  chunk_overlap: z.number().int().nonnegative(),
  created_at: z.string(),
  strategy: z.string().min(1),
  schema_version: z.number().int().positive(),
})
export type DocumentRecord = z.infer<typeof DocumentSchema>

export const DocumentsPageSchema = z.object({
  documents: z.array(DocumentSchema),
  total: z.number().int().nonnegative().nullable(),
  next_cursor: z.string().nullable(),
  truncated: z.boolean(),
})
export type DocumentsPage = z.infer<typeof DocumentsPageSchema>

export const ChunkSchema = z.object({
  point_id: z.string().min(1),
  chunk_index: z.number().int().nonnegative(),
  text: z.string(),
  token_count: z.number().int().nonnegative(),
  page: z.number().int().nonnegative().nullable(),
})
export type ChunkRecord = z.infer<typeof ChunkSchema>

export const ChunksPageSchema = z.object({
  chunks: z.array(ChunkSchema),
  next_cursor: z.string().nullable(),
  truncated: z.boolean(),
})
export type ChunksPage = z.infer<typeof ChunksPageSchema>

export const DeleteResponseSchema = z.object({
  status: z.literal("ok"),
  message: z.string(),
  deleted_count: z.number().int().nonnegative(),
})
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

export const ProgressResponseSchema = z.object({
  file_id: z.string().min(1),
  status: z.enum(["processing", "done", "error"]),
  message: z.string(),
  chunks_count: z.number().int().nonnegative().nullable().optional(),
  error: z.string().nullable().optional(),
})
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

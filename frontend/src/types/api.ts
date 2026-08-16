import { z } from "zod"

export const ChatSendRequestSchema = z.object({
  content: z.string().min(1).max(10_000),
  session_id: z.string().min(1).max(200).optional(),
  message_id: z.string().min(1).max(200).optional(),
})

export type ChatSendRequest = z.infer<typeof ChatSendRequestSchema>

export const ChatCancelResponseSchema = z.object({
  status: z.enum(["stopped", "idle"]),
  session_id: z.string().min(1),
})

export type ChatCancelResponse = z.infer<typeof ChatCancelResponseSchema>

const CitationSchema = z.object({
  source: z.string().optional(),
  filename: z.string().optional(),
  content: z.string().optional(),
  location: z.string().optional(),
  page: z.number().int().nonnegative().optional(),
})

export const ChatStartEventSchema = z.object({
  type: z.literal("start"),
  protocol: z.string().min(1),
  message_id: z.string().min(1),
  session_id: z.string().min(1),
})

export const ChatProgressEventSchema = z.object({
  type: z.literal("progress"),
  stage: z.string().min(1),
})

export const ChatTokenEventSchema = z.object({
  type: z.literal("token"),
  token: z.string().min(1),
  index: z.number().int().nonnegative().optional(),
  message_id: z.string().min(1).optional(),
})

const ChatCompletedDoneEventSchema = z.object({
  type: z.literal("done"),
  done: z.literal(true),
  completed: z.literal(true),
  message_id: z.string().min(1),
  full_response: z.string(),
  citations: z.array(CitationSchema).default([]),
  generated_from: z.string().optional(),
})

const ChatIncompleteDoneEventSchema = z.object({
  type: z.literal("done"),
  done: z.literal(true),
  completed: z.literal(false),
})

export const ChatDoneEventSchema = z.discriminatedUnion("completed", [
  ChatCompletedDoneEventSchema,
  ChatIncompleteDoneEventSchema,
])

export const ChatErrorEventSchema = z.object({
  type: z.literal("error"),
  code: z.string().regex(/^[a-z][a-z0-9_]{0,63}$/u),
  message: z.string().min(1),
  retryable: z.boolean(),
})

export const ChatStreamEventSchema = z.union([
  ChatStartEventSchema,
  ChatProgressEventSchema,
  ChatTokenEventSchema,
  ChatDoneEventSchema,
  ChatErrorEventSchema,
])

export type ChatStreamEvent = z.infer<typeof ChatStreamEventSchema>

import { z } from "zod"

import type { TranslationKey } from "../../i18n/locale-inventory"
import type { ChatStreamEvent } from "../../types/api"

export const CHAT_CONTENT_LIMIT = 10_000
export const ACTIVE_SESSION_STORAGE_KEY = "rag-studio-chat-session"

export const SessionSchema = z.object({
  created_at: z.string(),
  id: z.string().min(1),
  message_count: z.number().int().nonnegative().default(0),
  title: z.string(),
})
export const SessionListSchema = z.array(SessionSchema)
export type Session = z.infer<typeof SessionSchema>

const CitationSchema = z.object({
  content: z.string().optional(),
  filename: z.string().optional(),
  location: z.string().optional(),
  page: z.number().int().nonnegative().optional(),
  source: z.string().optional(),
})
export type Citation = z.infer<typeof CitationSchema>

export const ChatMessageSchema = z.object({
  citations: z.array(CitationSchema).optional(),
  content: z.string(),
  created_at: z.string(),
  generated_from: z.string().optional(),
  id: z.string().min(1),
  in_reply_to: z.string().optional(),
  role: z.enum(["user", "assistant"]),
})
export const ChatMessageListSchema = z.array(ChatMessageSchema)
export type ChatMessage = z.infer<typeof ChatMessageSchema>

export const SessionMutationResponseSchema = z.object({
  session_id: z.string().min(1),
  status: z.enum(["cleared", "deleted", "idle", "stopped"]),
})
export type SessionMutationResponse = z.infer<typeof SessionMutationResponseSchema>

export const FeedbackResponseSchema = z.object({
  feedback: z.enum(["positive", "negative"]),
  status: z.literal("saved"),
})
export type FeedbackResponse = z.infer<typeof FeedbackResponseSchema>

export type MessageCommitInput = {
  readonly content: string
  readonly message_id: string
}

export type FeedbackInput = {
  readonly feedback: "positive" | "negative"
  readonly message_id: string
  readonly reason?: string
  readonly session_id: string
}

export type ChatGateway = {
  cancel(sessionId: string): Promise<SessionMutationResponse>
  clearMessages(sessionId: string): Promise<SessionMutationResponse>
  commitMessage(sessionId: string, input: MessageCommitInput): Promise<ChatMessage>
  createSession(title: string): Promise<Session>
  deleteSession(sessionId: string): Promise<SessionMutationResponse>
  feedback(input: FeedbackInput): Promise<FeedbackResponse>
  listMessages(sessionId: string): Promise<readonly ChatMessage[]>
  listSessions(): Promise<readonly Session[]>
  renameSession(sessionId: string, title: string): Promise<Session>
}

export type ChatStreamOptions = {
  readonly onEvent: (event: ChatStreamEvent) => void
  readonly signal: AbortSignal
}

export type ChatStreamGateway = {
  cancel(sessionId: string): Promise<SessionMutationResponse>
  reattach(sessionId: string, options: ChatStreamOptions): Promise<void>
  send(
    input: { readonly content: string; readonly message_id: string; readonly session_id: string },
    options: ChatStreamOptions,
  ): Promise<void>
}

export type StreamState =
  | { readonly kind: "idle" }
  | { readonly kind: "connecting" }
  | { readonly kind: "streaming"; readonly stage: string }
  | { readonly kind: "completed" }
  | { readonly kind: "cancelled" }
  | {
      readonly kind: "error"
      readonly message: string
      readonly messageKey?: TranslationKey
      readonly retryAfterSeconds: number | null
    }

export type ChatSnapshot = {
  readonly activeSessionId: string | null
  readonly messages: readonly ChatMessage[]
  readonly partialResponse: string
  readonly sessions: readonly Session[]
  readonly stream: StreamState
}

export const INITIAL_CHAT_SNAPSHOT: ChatSnapshot = {
  activeSessionId: null,
  messages: [],
  partialResponse: "",
  sessions: [],
  stream: { kind: "idle" },
}

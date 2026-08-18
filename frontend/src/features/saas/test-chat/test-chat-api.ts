import { z } from "zod"

import { type ApiClient, apiClient } from "../../../api/client"
import {
  ApiContractError,
  apiErrorFromResponse,
  isAbortError,
  StreamCancelledError,
  StreamProtocolError,
} from "../../../api/errors"
import { SseFrameParser, type StreamOptions } from "../../../api/stream"

export type TestSession = {
  readonly session_id: string
  readonly title: string
  readonly created_at: string
  readonly updated_at: string
}

export type TestSessionCreateInput = {
  readonly session_id?: string
  readonly title?: string
}

export type TestChatMessageInput = {
  readonly content: string
  readonly locale: "en" | "ru"
}

export type TestChatFeedbackInput = {
  readonly message_id: string
  readonly feedback: "positive" | "negative"
  readonly reason?: string
}

export type TestChatOperation = {
  readonly status: "deleted" | "cancelled" | "idle" | "stored"
  readonly session_id: string
}

export type TestChatGateway = {
  readonly listSessions: (workspaceId: string, chatbotId: string) => Promise<readonly TestSession[]>
  readonly createSession: (
    workspaceId: string,
    chatbotId: string,
    input?: TestSessionCreateInput,
  ) => Promise<TestSession>
  readonly feedback: (
    workspaceId: string,
    chatbotId: string,
    sessionId: string,
    input: TestChatFeedbackInput,
  ) => Promise<TestChatOperation>
}

export type TestChatStreamOptions = StreamOptions

export type TestChatStreamGateway = {
  readonly send: (
    workspaceId: string,
    chatbotId: string,
    sessionId: string,
    input: TestChatMessageInput,
    options: TestChatStreamOptions,
  ) => Promise<void>
  readonly reattach: (
    workspaceId: string,
    chatbotId: string,
    sessionId: string,
    options: TestChatStreamOptions,
  ) => Promise<void>
  readonly cancel: (
    workspaceId: string,
    chatbotId: string,
    sessionId: string,
  ) => Promise<TestChatOperation>
}

const TestSessionSchema = z.object({
  session_id: z.string().uuid(),
  title: z.string().min(1).max(120),
  created_at: z.string().datetime({ offset: true }),
  updated_at: z.string().datetime({ offset: true }),
})

const TestChatOperationSchema = z.object({
  status: z.enum(["deleted", "cancelled", "idle", "stored"]),
  session_id: z.string().uuid(),
})

function chatbotPath(workspaceId: string, chatbotId: string): string {
  return `/api/saas/workspaces/${encodeURIComponent(workspaceId)}/chatbots/${encodeURIComponent(chatbotId)}`
}

function sessionPath(workspaceId: string, chatbotId: string, sessionId: string): string {
  return `${chatbotPath(workspaceId, chatbotId)}/sessions/${encodeURIComponent(sessionId)}`
}

function csrfToken(): string | null {
  if (typeof document === "undefined") return null
  const prefix = "__Host-ragstudio-csrf="
  const cookie = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix))
  return cookie === undefined ? null : decodeURIComponent(cookie.slice(prefix.length))
}

async function ensureCsrfToken(
  fetchImplementation: typeof fetch,
  signal: AbortSignal,
): Promise<string> {
  let token = csrfToken()
  if (token !== null && token !== "") return token
  const response = await fetchImplementation("/api/saas/auth/csrf", {
    credentials: "same-origin",
    signal,
  })
  if (!response.ok) throw apiErrorFromResponse(response)
  token = csrfToken()
  if (token === null || token === "") throw new ApiContractError()
  return token
}

async function consumeStream(response: Response, options: StreamOptions): Promise<void> {
  if (!response.ok) throw apiErrorFromResponse(response)
  if (response.body === null) throw new StreamProtocolError()
  const parser = new SseFrameParser()
  const decoder = new TextDecoder()
  const reader = response.body.getReader()
  try {
    while (true) {
      const read = await reader.read()
      if (read.done) break
      for (const event of parser.push(decoder.decode(read.value, { stream: true }))) {
        options.onEvent(event)
      }
    }
    for (const event of parser.push(decoder.decode())) options.onEvent(event)
    for (const event of parser.finish()) options.onEvent(event)
  } catch (error) {
    if (options.signal.aborted || isAbortError(error)) throw new StreamCancelledError()
    throw error
  } finally {
    reader.releaseLock()
  }
}

async function openTestStream(
  fetchImplementation: typeof fetch,
  path: string,
  init: RequestInit,
  options: StreamOptions,
): Promise<void> {
  let response: Response
  try {
    response = await fetchImplementation(path, {
      ...init,
      credentials: "same-origin",
      signal: options.signal,
    })
  } catch (error) {
    if (options.signal.aborted || isAbortError(error)) throw new StreamCancelledError()
    throw error
  }
  await consumeStream(response, options)
}

export function createTestChatGateway(client: ApiClient = apiClient): TestChatGateway {
  return {
    listSessions: (workspaceId, chatbotId) =>
      client.get(`${chatbotPath(workspaceId, chatbotId)}/sessions`, z.array(TestSessionSchema)),
    createSession: (workspaceId, chatbotId, input = {}) =>
      client.post(
        `${chatbotPath(workspaceId, chatbotId)}/sessions`,
        { title: input.title ?? "Test conversation", ...input },
        TestSessionSchema,
      ),
    feedback: (workspaceId, chatbotId, sessionId, input) =>
      client.post(
        `${sessionPath(workspaceId, chatbotId, sessionId)}/feedback`,
        input,
        TestChatOperationSchema,
      ),
  }
}

export function createTestChatStreamGateway(
  client: ApiClient = apiClient,
  fetchImplementation: typeof fetch = globalThis.fetch.bind(globalThis),
): TestChatStreamGateway {
  return {
    send: async (workspaceId, chatbotId, sessionId, input, options) => {
      const token = await ensureCsrfToken(fetchImplementation, options.signal)
      await openTestStream(
        fetchImplementation,
        `${sessionPath(workspaceId, chatbotId, sessionId)}/messages`,
        {
          body: JSON.stringify(input),
          headers: {
            Accept: "text/event-stream",
            "Content-Type": "application/json",
            "X-CSRF-Token": token,
          },
          method: "POST",
        },
        options,
      )
    },
    reattach: (workspaceId, chatbotId, sessionId, options) =>
      openTestStream(
        fetchImplementation,
        `${sessionPath(workspaceId, chatbotId, sessionId)}/stream`,
        { headers: { Accept: "text/event-stream" }, method: "GET" },
        options,
      ),
    cancel: (workspaceId, chatbotId, sessionId) =>
      client.post(
        `${sessionPath(workspaceId, chatbotId, sessionId)}/cancel`,
        {},
        TestChatOperationSchema,
      ),
  }
}

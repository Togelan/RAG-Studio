import { ApiClient } from "../../api/client"
import { cancelChatStream, reattachChatStream, streamChat } from "../../api/stream"
import {
  type ChatGateway,
  ChatMessageListSchema,
  ChatMessageSchema,
  type ChatStreamGateway,
  FeedbackResponseSchema,
  SessionListSchema,
  SessionMutationResponseSchema,
  SessionSchema,
} from "./model"

export function bindBrowserFetch(
  fetchImplementation: typeof fetch = globalThis.fetch,
): typeof fetch {
  return fetchImplementation.bind(globalThis)
}

function createBrowserApiClient(): ApiClient {
  return new ApiClient(bindBrowserFetch())
}

export function createChatGateway(client: ApiClient = createBrowserApiClient()): ChatGateway {
  return {
    cancel: (sessionId) =>
      client.post(
        `/api/chat/sessions/${encodeURIComponent(sessionId)}/cancel`,
        {},
        SessionMutationResponseSchema,
      ),
    clearMessages: (sessionId) =>
      client.delete(
        `/api/chat/sessions/${encodeURIComponent(sessionId)}/messages`,
        SessionMutationResponseSchema,
      ),
    commitMessage: (sessionId, input) =>
      client.post(
        `/api/chat/sessions/${encodeURIComponent(sessionId)}/messages`,
        input,
        ChatMessageSchema,
      ),
    createSession: (title) => client.post("/api/chat/sessions", { title }, SessionSchema),
    deleteSession: (sessionId) =>
      client.delete(
        `/api/chat/sessions/${encodeURIComponent(sessionId)}`,
        SessionMutationResponseSchema,
      ),
    feedback: (input) => client.post("/api/chat/feedback", input, FeedbackResponseSchema),
    listMessages: (sessionId) =>
      client.get(
        `/api/chat/sessions/${encodeURIComponent(sessionId)}/messages`,
        ChatMessageListSchema,
      ),
    listSessions: () => client.get("/api/chat/sessions", SessionListSchema),
    renameSession: (sessionId, title) =>
      client.patch(`/api/chat/sessions/${encodeURIComponent(sessionId)}`, { title }, SessionSchema),
  }
}

export const defaultChatGateway = createChatGateway()

export const defaultChatStreamGateway: ChatStreamGateway = {
  cancel: (sessionId) => cancelChatStream(sessionId, undefined, createBrowserApiClient()),
  reattach: reattachChatStream,
  send: streamChat,
}

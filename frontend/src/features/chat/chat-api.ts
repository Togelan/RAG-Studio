import { z } from "zod"
import { ApiClient } from "../../api/client"
import { cancelChatStream, reattachChatStream, streamChat } from "../../api/stream"
import {
  type ChatGateway,
  ChatMessageListSchema,
  ChatMessageSchema,
  type ChatStreamGateway,
  SessionListSchema,
  SessionMutationResponseSchema,
  SessionSchema,
} from "./model"

const PERSONAL_CHAT_PATH = "/api/personal/chat" as const
const PersonalFeedbackResponseSchema = z.object({
  feedback: z.enum(["like", "dislike"]),
  id: z.string().min(1),
  status: z.literal("saved"),
})

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
        `${PERSONAL_CHAT_PATH}/sessions/${encodeURIComponent(sessionId)}/cancel`,
        {},
        SessionMutationResponseSchema,
      ),
    clearMessages: (sessionId) =>
      client.delete(
        `${PERSONAL_CHAT_PATH}/sessions/${encodeURIComponent(sessionId)}/messages`,
        SessionMutationResponseSchema,
      ),
    commitMessage: (sessionId, input) =>
      client.post(
        `${PERSONAL_CHAT_PATH}/sessions/${encodeURIComponent(sessionId)}/messages`,
        input,
        ChatMessageSchema,
      ),
    createSession: (title) =>
      client.post(`${PERSONAL_CHAT_PATH}/sessions`, { title }, SessionSchema),
    deleteSession: (sessionId) =>
      client.delete(
        `${PERSONAL_CHAT_PATH}/sessions/${encodeURIComponent(sessionId)}`,
        SessionMutationResponseSchema,
      ),
    feedback: async (input) => {
      const response = await client.post(
        `${PERSONAL_CHAT_PATH}/feedback`,
        {
          feedback: input.feedback === "positive" ? "like" : "dislike",
          message_id: input.message_id,
          ...(input.reason === undefined ? {} : { reason: input.reason }),
          session_id: input.session_id,
        },
        PersonalFeedbackResponseSchema,
      )
      return {
        feedback: response.feedback === "like" ? "positive" : "negative",
        status: response.status,
      }
    },
    listMessages: (sessionId) =>
      client.get(
        `${PERSONAL_CHAT_PATH}/sessions/${encodeURIComponent(sessionId)}/messages`,
        ChatMessageListSchema,
      ),
    listSessions: () => client.get(`${PERSONAL_CHAT_PATH}/sessions`, SessionListSchema),
    renameSession: (sessionId, title) =>
      client.patch(
        `${PERSONAL_CHAT_PATH}/sessions/${encodeURIComponent(sessionId)}`,
        { title },
        SessionSchema,
      ),
  }
}

export const defaultChatGateway = createChatGateway()

export const defaultChatStreamGateway: ChatStreamGateway = {
  cancel: (sessionId) => cancelChatStream(sessionId, undefined, createBrowserApiClient()),
  reattach: reattachChatStream,
  send: streamChat,
}

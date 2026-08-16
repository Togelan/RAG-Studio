import { ApiContractError, ApiError, StreamProtocolError } from "../../api/errors"
import type { ChatStreamEvent } from "../../types/api"
import type { ChatMessage, ChatSnapshot, Session, StreamState } from "./model"

export type FrameScheduler = (callback: () => void) => void

type NonTokenStreamEvent = Exclude<ChatStreamEvent, { readonly type: "token" }>

export type StreamEventTransition = {
  readonly clearPendingTokens: boolean
  readonly snapshot: ChatSnapshot | null
  readonly terminal: boolean
}

export function scheduleFrame(callback: () => void): void {
  if (typeof globalThis.requestAnimationFrame === "function") {
    globalThis.requestAnimationFrame(callback)
    return
  }
  globalThis.setTimeout(callback, 0)
}

export function userMessage(content: string, id: string): ChatMessage {
  return { content, created_at: new Date().toISOString(), id, role: "user" }
}

export function errorState(error: unknown): StreamState {
  if (error instanceof ApiError) {
    if (error.status === 404) {
      return {
        kind: "error",
        message: "This conversation is no longer available.",
        messageKey: "chat_stream_failed",
        retryAfterSeconds: null,
      }
    }
    if (error.status === 409) {
      return {
        kind: "error",
        message: "A response is already running for this conversation.",
        messageKey: "chat_stream_conflict",
        retryAfterSeconds: null,
      }
    }
    if (error.status === 429) {
      return {
        kind: "error",
        message: "Too many requests. Try again shortly.",
        messageKey: "chat_stream_capacity",
        retryAfterSeconds: error.retryAfterSeconds,
      }
    }
    if (error.status === 503) {
      return {
        kind: "error",
        message: "Chat is at capacity. Try again shortly.",
        messageKey: "chat_stream_capacity",
        retryAfterSeconds: error.retryAfterSeconds,
      }
    }
    return {
      kind: "error",
      message: error.messageForUser,
      messageKey: "chat_stream_failed",
      retryAfterSeconds: error.retryAfterSeconds,
    }
  }
  if (error instanceof StreamProtocolError || error instanceof ApiContractError) {
    return {
      kind: "error",
      message: "The response stream ended unexpectedly.",
      messageKey: "chat_stream_failed",
      retryAfterSeconds: null,
    }
  }
  return {
    kind: "error",
    message: "The response could not be completed.",
    messageKey: "chat_stream_failed",
    retryAfterSeconds: null,
  }
}

export function updateMessageCount(
  sessions: readonly Session[],
  sessionId: string,
  messageCount: number,
): readonly Session[] {
  return sessions.map((session) =>
    session.id === sessionId ? { ...session, message_count: messageCount } : session,
  )
}

export function replaceSession(sessions: readonly Session[], updated: Session): readonly Session[] {
  return sessions.map((session) => (session.id === updated.id ? updated : session))
}

export function removeSession(snapshot: ChatSnapshot, sessionId: string): ChatSnapshot {
  const removingActive = snapshot.activeSessionId === sessionId
  return {
    ...snapshot,
    activeSessionId: removingActive ? null : snapshot.activeSessionId,
    messages: removingActive ? [] : snapshot.messages,
    sessions: snapshot.sessions.filter((session) => session.id !== sessionId),
  }
}

export function reduceStreamEvent(
  snapshot: ChatSnapshot,
  event: NonTokenStreamEvent,
  sessionId: string,
): StreamEventTransition {
  if (event.type === "start") {
    return {
      clearPendingTokens: false,
      snapshot: { ...snapshot, stream: { kind: "streaming", stage: "starting" } },
      terminal: false,
    }
  }
  if (event.type === "progress") {
    return {
      clearPendingTokens: false,
      snapshot: { ...snapshot, stream: { kind: "streaming", stage: event.stage } },
      terminal: false,
    }
  }
  if (event.type === "error") {
    return {
      clearPendingTokens: false,
      snapshot: {
        ...snapshot,
        partialResponse: "",
        stream: {
          kind: "error",
          message: event.message,
          messageKey: "chat_stream_failed",
          retryAfterSeconds: null,
        },
      },
      terminal: true,
    }
  }
  if (!event.completed) {
    return {
      clearPendingTokens: true,
      snapshot:
        snapshot.stream.kind === "error"
          ? null
          : {
              ...snapshot,
              partialResponse: "",
              stream: {
                kind: "error",
                message: "The response was not completed.",
                messageKey: "chat_stream_failed",
                retryAfterSeconds: null,
              },
            },
      terminal: true,
    }
  }
  return {
    clearPendingTokens: true,
    snapshot: {
      ...snapshot,
      messages: [
        ...snapshot.messages,
        {
          citations: event.citations,
          content: event.full_response,
          created_at: new Date().toISOString(),
          ...(event.generated_from ? { generated_from: event.generated_from } : {}),
          id: event.message_id,
          role: "assistant",
        },
      ],
      partialResponse: "",
      sessions: updateMessageCount(snapshot.sessions, sessionId, snapshot.messages.length + 1),
      stream: { kind: "completed" },
    },
    terminal: true,
  }
}

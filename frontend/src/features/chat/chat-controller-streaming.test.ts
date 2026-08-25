import { describe, expect, it, vi } from "vitest"

import { ApiError, StreamProtocolError } from "../../api/errors"
import { ChatController } from "./chat-controller"
import type {
  ChatGateway,
  ChatMessage,
  ChatStreamGateway,
  FeedbackInput,
  FeedbackResponse,
  MessageCommitInput,
  Session,
  SessionMutationResponse,
} from "./model"

const SESSION: Session = {
  created_at: "2026-08-15T00:00:00Z",
  id: "session-a",
  message_count: 0,
  title: "Research",
}

function gateway(): ChatGateway {
  const mutation = async (
    status: SessionMutationResponse["status"],
  ): Promise<SessionMutationResponse> => ({ session_id: SESSION.id, status })
  return {
    cancel: vi.fn(async () => mutation("stopped")),
    clearMessages: vi.fn(async () => mutation("cleared")),
    commitMessage: vi.fn(
      async (_sessionId: string, input: MessageCommitInput): Promise<ChatMessage> => ({
        content: input.content,
        created_at: "",
        id: input.message_id,
        role: "user",
      }),
    ),
    createSession: vi.fn(async () => SESSION),
    deleteSession: vi.fn(async () => mutation("deleted")),
    feedback: vi.fn(
      async (_input: FeedbackInput): Promise<FeedbackResponse> => ({
        feedback: "positive",
        status: "saved",
      }),
    ),
    listMessages: vi.fn(async () => []),
    listSessions: vi.fn(async () => [SESSION]),
    renameSession: vi.fn(async (_id, title) => ({ ...SESSION, title })),
  }
}

describe("ChatController stream failures", () => {
  it.each([
    [
      new ApiError(401, "The request could not be completed. Please try again.", null),
      "could not be completed",
      "chat_stream_failed",
      null,
    ],
    [
      new ApiError(403, "The request could not be completed. Please try again.", null),
      "could not be completed",
      "chat_stream_failed",
      null,
    ],
    [
      new ApiError(404, "The request could not be completed. Please try again.", null),
      "no longer available",
      "chat_stream_failed",
      null,
    ],
    [new ApiError(409, "raw conflict", null), "already running", "chat_stream_conflict", null],
    [new ApiError(429, "raw overload", 7), "Too many requests", "chat_stream_capacity", 7],
    [new ApiError(503, "raw failure", 3), "at capacity", "chat_stream_capacity", 3],
    [new StreamProtocolError(), "ended unexpectedly", "chat_stream_failed", null],
  ])("sanitizes stream failure %#", async (failure, message, messageKey, retryAfterSeconds) => {
    const api = gateway()
    const controller = new ChatController(
      api,
      {
        cancel: api.cancel,
        reattach: vi.fn(async () => undefined),
        send: vi.fn(async () => {
          throw failure
        }),
      },
      () => "user-a",
    )
    await controller.load()
    await controller.selectSession(SESSION.id, false)
    await controller.send("Fail safely")

    expect(controller.snapshot().stream).toEqual({
      kind: "error",
      message: expect.stringContaining(message),
      messageKey,
      retryAfterSeconds,
    })
    expect(JSON.stringify(controller.snapshot())).not.toContain("raw ")
  })

  it("batches token bursts into one measured DOM frame", async () => {
    const api = gateway()
    const frames: Array<() => void> = []
    const measure = vi.spyOn(performance, "measure")
    const streams: ChatStreamGateway = {
      cancel: api.cancel,
      reattach: vi.fn(async () => undefined),
      send: vi.fn(
        (_input, options) =>
          new Promise<void>((resolve) => {
            options.onEvent({
              message_id: "assistant-a",
              protocol: "1",
              session_id: SESSION.id,
              type: "start",
            })
            options.onEvent({ token: "one ", type: "token" })
            options.onEvent({ token: "two ", type: "token" })
            options.onEvent({ token: "three", type: "token" })
            options.signal.addEventListener("abort", () => resolve(), { once: true })
          }),
      ),
    }
    const controller = new ChatController(
      api,
      streams,
      () => "user-a",
      (frame) => frames.push(frame),
    )
    await controller.load()
    await controller.selectSession(SESSION.id, false)
    const sending = controller.send("Batch tokens")
    await vi.waitFor(() => expect(frames).toHaveLength(1))
    frames[0]?.()

    expect(controller.snapshot().partialResponse).toBe("one two three")
    expect(measure).toHaveBeenCalledWith(
      "rag-chat-response-to-dom",
      "rag-chat-token-received",
      "rag-chat-token-painted",
    )
    await controller.stop()
    await sending
  })
})

import { describe, expect, it, vi } from "vitest"

import type { ChatStreamEvent } from "../../types/api"
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

describe("ChatController", () => {
  it("commits the user message before opening a stream and completes from public events", async () => {
    const calls: string[] = []
    const api = gateway()
    api.commitMessage = vi.fn(
      async (_sessionId: string, input: MessageCommitInput): Promise<ChatMessage> => {
        calls.push("commit")
        return { content: input.content, created_at: "", id: input.message_id, role: "user" }
      },
    )
    const streams: ChatStreamGateway = {
      cancel: api.cancel,
      reattach: vi.fn(async () => undefined),
      send: vi.fn(async (_input, options) => {
        calls.push("stream")
        options.onEvent({
          message_id: "assistant-a",
          protocol: "1",
          session_id: SESSION.id,
          type: "start",
        })
        options.onEvent({ type: "token", token: "Grounded " })
        options.onEvent({ type: "token", token: "answer" })
        options.onEvent({
          citations: [{ filename: "guide.md", location: "Section 2" }],
          completed: true,
          done: true,
          full_response: "Grounded answer",
          message_id: "assistant-a",
          type: "done",
        })
      }),
    }
    const controller = new ChatController(api, streams, () => "user-a")
    await controller.load()
    await controller.selectSession(SESSION.id, false)
    await controller.send("Where is the evidence?")

    expect(calls).toEqual(["commit", "stream"])
    expect(controller.snapshot().messages).toEqual([
      expect.objectContaining({ content: "Where is the evidence?", role: "user" }),
      expect.objectContaining({
        citations: [{ filename: "guide.md", location: "Section 2" }],
        content: "Grounded answer",
        id: "assistant-a",
        role: "assistant",
      }),
    ])
    expect(controller.snapshot().stream.kind).toBe("completed")
    expect(controller.snapshot().sessions[0]?.message_count).toBe(2)
  })

  it("ignores stale events after switching sessions and never persists an incomplete assistant", async () => {
    let emit: (event: ChatStreamEvent) => void = () => undefined
    const api = gateway()
    const second = { ...SESSION, id: "session-b", title: "Second" }
    api.listSessions = vi.fn(async () => [SESSION, second])
    const streams: ChatStreamGateway = {
      cancel: api.cancel,
      reattach: vi.fn(async () => undefined),
      send: vi.fn(
        (_input, options) =>
          new Promise<void>((resolve) => {
            emit = options.onEvent
            options.signal.addEventListener("abort", () => resolve(), { once: true })
          }),
      ),
    }
    const controller = new ChatController(api, streams, () => "user-a")
    await controller.load()
    await controller.selectSession(SESSION.id, false)
    const sending = controller.send("First")
    await vi.waitFor(() => expect(streams.send).toHaveBeenCalled())
    emit({ type: "token", token: "partial" })
    await controller.selectSession(second.id, false)
    emit({
      citations: [],
      completed: true,
      done: true,
      full_response: "stale",
      message_id: "assistant-stale",
      type: "done",
    })
    await sending

    expect(controller.snapshot().activeSessionId).toBe(second.id)
    expect(controller.snapshot().messages).toEqual([])
  })

  it("cancels the backend on Stop and surfaces bounded status messages", async () => {
    const api = gateway()
    const streams: ChatStreamGateway = {
      cancel: api.cancel,
      reattach: vi.fn(async () => undefined),
      send: vi.fn(
        (_input, options) =>
          new Promise<void>((resolve) => {
            options.signal.addEventListener("abort", () => resolve(), { once: true })
          }),
      ),
    }
    const controller = new ChatController(api, streams, () => "user-a")
    await controller.load()
    await controller.selectSession(SESSION.id, false)
    const sending = controller.send("Stop me")
    await vi.waitFor(() => expect(streams.send).toHaveBeenCalled())
    await controller.stop()
    await sending

    expect(api.cancel).toHaveBeenCalledWith(SESSION.id)
    expect(controller.snapshot().messages).toHaveLength(1)
    expect(controller.snapshot().stream.kind).toBe("cancelled")
  })

  it("discards a painted partial immediately and ignores done while cancel is pending", async () => {
    const api = gateway()
    let emit: (event: ChatStreamEvent) => void = () => undefined
    let finishStream = (): void => undefined
    let finishCancel = (): void => undefined
    const streams: ChatStreamGateway = {
      cancel: vi.fn(
        () =>
          new Promise<SessionMutationResponse>((resolve) => {
            finishCancel = () => resolve({ session_id: SESSION.id, status: "stopped" })
          }),
      ),
      reattach: vi.fn(async () => undefined),
      send: vi.fn(
        (_input, options) =>
          new Promise<void>((resolve) => {
            emit = options.onEvent
            finishStream = resolve
            emit({
              message_id: "assistant-a",
              protocol: "1",
              session_id: SESSION.id,
              type: "start",
            })
            emit({ token: "partial answer", type: "token" })
          }),
      ),
    }
    const controller = new ChatController(
      api,
      streams,
      () => "user-a",
      (frame) => frame(),
    )
    await controller.load()
    await controller.selectSession(SESSION.id, false)
    const sending = controller.send("Stop this response")
    await vi.waitFor(() => expect(controller.snapshot().partialResponse).toBe("partial answer"))

    const stopping = controller.stop()
    expect(controller.snapshot().partialResponse).toBe("")
    expect(controller.snapshot().stream.kind).toBe("cancelled")

    emit({
      citations: [{ filename: "late.md" }],
      completed: true,
      done: true,
      full_response: "late completed answer",
      message_id: "assistant-late",
      type: "done",
    })
    finishStream()
    finishCancel()
    await Promise.all([sending, stopping])

    expect(controller.snapshot().messages).toEqual([
      expect.objectContaining({ content: "Stop this response", role: "user" }),
    ])
    expect(controller.snapshot().sessions[0]?.message_count).toBe(1)
    expect(JSON.stringify(controller.snapshot())).not.toContain("late completed answer")
  })

  it("supports session CRUD and reattaches only when explicitly requested", async () => {
    const api = gateway()
    api.listSessions = vi.fn(async () => [{ ...SESSION, message_count: 3 }])
    const streams: ChatStreamGateway = {
      cancel: api.cancel,
      reattach: vi.fn(async () => undefined),
      send: vi.fn(async () => undefined),
    }
    const controller = new ChatController(api, streams, () => "user-a")
    await controller.load()
    await controller.selectSession(SESSION.id, false)
    expect(streams.reattach).not.toHaveBeenCalled()

    await controller.renameSession(SESSION.id, " Renamed ")
    expect(controller.snapshot().sessions[0]?.title).toBe("Renamed")
    expect(controller.snapshot().sessions[0]?.message_count).toBe(3)
    await controller.clearMessages()
    expect(controller.snapshot().sessions[0]?.message_count).toBe(0)
    await controller.selectSession(SESSION.id)
    expect(streams.reattach).toHaveBeenCalledOnce()
    await controller.deleteSession(SESSION.id)
    expect(controller.snapshot().activeSessionId).toBeNull()
    expect(controller.snapshot().sessions).toEqual([])
    await controller.createSession()
    expect(controller.snapshot().activeSessionId).toBe(SESSION.id)
  })
})

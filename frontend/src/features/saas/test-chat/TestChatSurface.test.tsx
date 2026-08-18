import { cleanup, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { SseFrameParser } from "../../../api/stream"
import type { ChatStreamEvent } from "../../../types/api"
import { TestChatSurface } from "./TestChatSurface"
import type {
  TestChatGateway,
  TestChatOperation,
  TestChatStreamGateway,
  TestSession,
} from "./test-chat-api"

const workspaceId = "00000000-0000-4000-8000-000000000010"
const chatbotId = "00000000-0000-4000-8000-000000000020"
const sessionId = "00000000-0000-4000-8000-000000000040"

const savedSession: TestSession = {
  session_id: sessionId,
  title: "Saved test",
  created_at: "2026-08-17T10:00:00Z",
  updated_at: "2026-08-17T10:00:00Z",
}

function gateway(sessions: readonly TestSession[] = []): TestChatGateway {
  return {
    createSession: vi.fn(() => Promise.resolve(savedSession)),
    feedback: vi.fn(() =>
      Promise.resolve({ status: "stored", session_id: sessionId } satisfies TestChatOperation),
    ),
    listSessions: vi.fn(() => Promise.resolve(sessions)),
  }
}

function emitCompleted(onEvent: (event: ChatStreamEvent) => void): void {
  onEvent({ type: "token", token: "Approved answer" })
  onEvent({
    type: "done",
    done: true,
    completed: true,
    message_id: "00000000-0000-4000-8000-000000000050",
    full_response: "Approved answer",
    citations: [
      {
        content: "Approved guidance is recorded in the handbook.",
        filename: "handbook.pdf",
        location: "Section 2.3",
        page: 3,
      },
    ],
  })
}

function emitSaasCompletedDone(onEvent: (event: ChatStreamEvent) => void): void {
  const parser = new SseFrameParser()
  const frames = [
    'event: token\ndata: {"token":"Final BFF answer"}\n\n',
    'event: done\ndata: {"done":true,"completed":true,"message_id":"00000000-0000-4000-8000-000000000050","full_response":"Final BFF answer","generated_from":"retrieval","citations":[{"filename":"handbook.pdf"}]}\n\n',
  ].join("")
  for (const event of parser.push(frames)) onEvent(event)
}

function streamGateway(): TestChatStreamGateway {
  return {
    cancel: vi.fn(() =>
      Promise.resolve({ status: "cancelled", session_id: sessionId } satisfies TestChatOperation),
    ),
    reattach: vi.fn((_workspaceId, _chatbotId, _sessionId, options) => {
      emitCompleted(options.onEvent)
      return Promise.resolve()
    }),
    send: vi.fn((_workspaceId, _chatbotId, _sessionId, _input, options) => {
      emitCompleted(options.onEvent)
      return Promise.resolve()
    }),
  }
}

describe("Test chat surface", () => {
  afterEach(cleanup)

  it("creates a test session, streams citations, and stores feedback", async () => {
    // Given: an enabled chatbot with no previous test conversation.
    const user = userEvent.setup()
    const api = gateway()
    const stream = streamGateway()
    render(
      <TestChatSurface
        chatbotId={chatbotId}
        gateway={api}
        locale="en"
        streamGateway={stream}
        workspaceId={workspaceId}
      />,
    )

    // When: the user starts a conversation, sends a prompt, and rates the completed answer.
    await user.click(await screen.findByRole("button", { name: "Start test conversation" }))
    await user.type(screen.getByLabelText("Message"), "What is approved?")
    await user.click(screen.getByRole("button", { name: "Send" }))
    await user.click(await screen.findByRole("button", { name: "Helpful" }))

    // Then: the tenant scope, locale, citations, and assistant message ID remain intact.
    expect(stream.send).toHaveBeenCalledWith(
      workspaceId,
      chatbotId,
      sessionId,
      { content: "What is approved?", locale: "en" },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    expect(screen.getByText("Approved answer")).toBeVisible()
    expect(screen.getByText("Citation 1: handbook.pdf")).toBeVisible()
    await user.click(screen.getByText("Citation 1: handbook.pdf"))
    expect(screen.getByText("Reference")).toBeVisible()
    expect(screen.getByText("00000000-0000-4000-8000-000000000050-1")).toBeVisible()
    expect(screen.getByText("Section 2.3")).toBeVisible()
    expect(screen.getByText("Approved guidance is recorded in the handbook.")).toBeVisible()
    expect(api.feedback).toHaveBeenCalledWith(workspaceId, chatbotId, sessionId, {
      message_id: "00000000-0000-4000-8000-000000000050",
      feedback: "positive",
    })
  })

  it("renders the shared completed terminal event without a false failure", async () => {
    // Given: the BFF emits the shared completed terminal payload.
    const user = userEvent.setup()
    const stream = streamGateway()
    vi.mocked(stream.send).mockImplementation(
      (_workspaceId, _chatbotId, _sessionId, _input, options) => {
        emitSaasCompletedDone(options.onEvent)
        return Promise.resolve()
      },
    )
    render(
      <TestChatSurface
        chatbotId={chatbotId}
        gateway={gateway([savedSession])}
        locale="en"
        streamGateway={stream}
        workspaceId={workspaceId}
      />,
    )

    // When: the user sends a message through the BFF event sequence.
    await user.click(await screen.findByRole("button", { name: "Saved test" }))
    await user.type(screen.getByLabelText("Message"), "What is approved?")
    await user.click(screen.getByRole("button", { name: "Send" }))

    // Then: the answer and feedback remain visible without a false failure status.
    expect(await screen.findByText("Final BFF answer")).toBeVisible()
    expect(screen.getByRole("button", { name: "Helpful" })).toBeVisible()
    expect(screen.queryByRole("button", { name: "Reattach response" })).toBeNull()
    expect(screen.getByRole("status")).toHaveTextContent("Response complete.")
  })

  it("reattaches an existing response through the exact composite scope", async () => {
    // Given: a persisted test session whose response can still be replayed.
    const user = userEvent.setup()
    const stream = streamGateway()
    render(
      <TestChatSurface
        chatbotId={chatbotId}
        gateway={gateway([savedSession])}
        locale="en"
        streamGateway={stream}
        workspaceId={workspaceId}
      />,
    )

    // When: the user selects the session and requests reattachment.
    await user.click(await screen.findByRole("button", { name: "Saved test" }))
    await user.click(screen.getByRole("button", { name: "Reattach response" }))

    // Then: replay uses workspace, chatbot, and session IDs and restores the completed answer.
    expect(stream.reattach).toHaveBeenCalledWith(
      workspaceId,
      chatbotId,
      sessionId,
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    expect(await screen.findByText("Approved answer")).toBeVisible()
  })

  it("cancels an active response at both browser and server boundaries", async () => {
    // Given: a selected session with a response that remains active until aborted.
    const user = userEvent.setup()
    const stream = streamGateway()
    vi.mocked(stream.send).mockImplementation(
      (_workspaceId, _chatbotId, _sessionId, _input, options) =>
        new Promise<void>((_resolve, reject) => {
          options.signal.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError")),
          )
        }),
    )
    render(
      <TestChatSurface
        chatbotId={chatbotId}
        gateway={gateway([savedSession])}
        locale="en"
        streamGateway={stream}
        workspaceId={workspaceId}
      />,
    )

    // When: the user sends a prompt and cancels while streaming.
    await user.click(await screen.findByRole("button", { name: "Saved test" }))
    await user.type(screen.getByLabelText("Message"), "Stop this response")
    await user.click(screen.getByRole("button", { name: "Send" }))
    await user.click(await screen.findByRole("button", { name: "Cancel response" }))

    // Then: the local request is aborted and the server-scoped cancel endpoint is called.
    expect(stream.cancel).toHaveBeenCalledWith(workspaceId, chatbotId, sessionId)
    expect(await screen.findByText("Response cancelled.")).toBeVisible()
  })
})

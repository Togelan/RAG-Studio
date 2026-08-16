import { describe, expect, it } from "vitest"

import { ApiError, StreamProtocolError } from "../../api/errors"
import {
  errorState,
  reduceStreamEvent,
  removeSession,
  replaceSession,
  updateMessageCount,
} from "./chat-controller-runtime"
import type { ChatSnapshot, Session } from "./model"

const FIRST_SESSION: Session = {
  created_at: "2026-08-15T00:00:00Z",
  id: "session-a",
  message_count: 1,
  title: "First",
}
const SECOND_SESSION: Session = {
  ...FIRST_SESSION,
  id: "session-b",
  message_count: 0,
  title: "Second",
}
const SNAPSHOT: ChatSnapshot = {
  activeSessionId: FIRST_SESSION.id,
  messages: [
    {
      content: "Question",
      created_at: "2026-08-15T00:00:00Z",
      id: "user-a",
      role: "user",
    },
  ],
  partialResponse: "Partial",
  sessions: [FIRST_SESSION, SECOND_SESSION],
  stream: { kind: "connecting" },
}

describe("chat controller runtime", () => {
  it("reduces bounded non-terminal stream states without mutating the source snapshot", () => {
    const started = reduceStreamEvent(
      SNAPSHOT,
      { message_id: "assistant-a", protocol: "1", session_id: FIRST_SESSION.id, type: "start" },
      FIRST_SESSION.id,
    )
    const progressed = reduceStreamEvent(
      SNAPSHOT,
      { stage: "retrieving", type: "progress" },
      FIRST_SESSION.id,
    )

    expect(started).toEqual({
      clearPendingTokens: false,
      snapshot: { ...SNAPSHOT, stream: { kind: "streaming", stage: "starting" } },
      terminal: false,
    })
    expect(progressed.snapshot?.stream).toEqual({ kind: "streaming", stage: "retrieving" })
    expect(SNAPSHOT.stream).toEqual({ kind: "connecting" })
  })

  it("persists only completed assistant responses with citations and provenance", () => {
    const transition = reduceStreamEvent(
      SNAPSHOT,
      {
        citations: [{ filename: "guide.md", location: "Section 2" }],
        completed: true,
        done: true,
        full_response: "Grounded answer",
        generated_from: "user-a",
        message_id: "assistant-a",
        type: "done",
      },
      FIRST_SESSION.id,
    )

    expect(transition.terminal).toBe(true)
    expect(transition.clearPendingTokens).toBe(true)
    expect(transition.snapshot?.messages).toEqual([
      SNAPSHOT.messages[0],
      expect.objectContaining({
        citations: [{ filename: "guide.md", location: "Section 2" }],
        content: "Grounded answer",
        generated_from: "user-a",
        id: "assistant-a",
        role: "assistant",
      }),
    ])
    expect(transition.snapshot?.sessions[0]?.message_count).toBe(2)
  })

  it("discards incomplete output and preserves an existing sanitized stream error", () => {
    const incomplete = reduceStreamEvent(
      SNAPSHOT,
      { completed: false, done: true, type: "done" },
      FIRST_SESSION.id,
    )
    const failedSnapshot: ChatSnapshot = {
      ...SNAPSHOT,
      stream: { kind: "error", message: "Safe error", retryAfterSeconds: null },
    }
    const afterError = reduceStreamEvent(
      failedSnapshot,
      { completed: false, done: true, type: "done" },
      FIRST_SESSION.id,
    )

    expect(incomplete.snapshot).toEqual({
      ...SNAPSHOT,
      partialResponse: "",
      stream: {
        kind: "error",
        message: "The response was not completed.",
        messageKey: "chat_stream_failed",
        retryAfterSeconds: null,
      },
    })
    expect(afterError.snapshot).toBeNull()
  })

  it("tags a sanitized SSE error for locale rendering", () => {
    const transition = reduceStreamEvent(
      SNAPSHOT,
      {
        code: "generation_failed",
        message: "The response could not be completed. Please try again.",
        retryable: true,
        type: "error",
      },
      FIRST_SESSION.id,
    )

    expect(transition.snapshot?.stream).toEqual({
      kind: "error",
      message: "The response could not be completed. Please try again.",
      messageKey: "chat_stream_failed",
      retryAfterSeconds: null,
    })
  })

  it("keeps session transforms immutable for count, rename, and active deletion", () => {
    const counted = updateMessageCount(SNAPSHOT.sessions, FIRST_SESSION.id, 4)
    const renamed = replaceSession(counted, {
      ...FIRST_SESSION,
      message_count: 4,
      title: "Renamed",
    })
    const removed = removeSession({ ...SNAPSHOT, sessions: renamed }, FIRST_SESSION.id)

    expect(SNAPSHOT.sessions[0]).toEqual(FIRST_SESSION)
    expect(renamed[0]).toEqual({ ...FIRST_SESSION, message_count: 4, title: "Renamed" })
    expect(removed.activeSessionId).toBeNull()
    expect(removed.messages).toEqual([])
    expect(removed.sessions).toEqual([SECOND_SESSION])
  })

  it("maps transport and protocol failures to bounded user-facing errors", () => {
    expect(errorState(new ApiError(429, "raw overload", 7))).toEqual({
      kind: "error",
      message: "Too many requests. Try again shortly.",
      messageKey: "chat_stream_capacity",
      retryAfterSeconds: 7,
    })
    expect(errorState(new StreamProtocolError())).toEqual({
      kind: "error",
      message: "The response stream ended unexpectedly.",
      messageKey: "chat_stream_failed",
      retryAfterSeconds: null,
    })
  })
})

import type { ChatCancelResponse, ChatSendRequest, ChatStreamEvent } from "../types/api"
import {
  ChatCancelResponseSchema,
  ChatSendRequestSchema,
  ChatStreamEventSchema,
} from "../types/api"
import { type ApiClient, apiClient } from "./client"
import { browserCsrfToken, csrfHeadersForMutation } from "./csrf"
import {
  apiErrorFromResponse,
  isAbortError,
  StreamCancelledError,
  StreamProtocolError,
} from "./errors"

export type StreamCallbacks = {
  readonly onEvent: (event: ChatStreamEvent) => void
}

export type StreamOptions = StreamCallbacks & {
  readonly signal: AbortSignal
}

type StreamIdentity = {
  readonly messageId?: string
  readonly sessionId?: string
}

type MutableEventData = {
  completed?: unknown
  full_response?: unknown
  message_id?: unknown
  type?: unknown
} & Record<string, unknown>

function nextFrameBoundary(buffer: string): number {
  const crlfBoundary = buffer.indexOf("\r\n\r\n")
  const lfBoundary = buffer.indexOf("\n\n")

  if (crlfBoundary === -1) {
    return lfBoundary
  }
  if (lfBoundary === -1) {
    return crlfBoundary
  }
  return Math.min(crlfBoundary, lfBoundary)
}

function frameLengthAt(buffer: string, boundary: number): number {
  return buffer.startsWith("\r\n\r\n", boundary) ? 4 : 2
}

function normalizePersonalEvent(
  eventName: string,
  eventData: MutableEventData,
  identity: StreamIdentity,
): void {
  if (eventName === "start" && typeof eventData.message_id !== "string") {
    const messageId = identity.messageId ?? identity.sessionId
    if (messageId !== undefined) eventData.message_id = messageId
  }
  if (
    eventName === "done" &&
    eventData.completed === false &&
    typeof eventData.full_response === "string" &&
    typeof eventData.message_id === "string"
  ) {
    eventData.completed = true
  }
}

function parseFrame(frame: string, identity: StreamIdentity = {}): ChatStreamEvent | null {
  if (frame.startsWith(":")) {
    return null
  }

  let eventName = "message"
  const dataLines: string[] = []
  for (const line of frame.split(/\r?\n/u)) {
    if (line.startsWith("event:")) {
      eventName = line.slice(6).trim() || "message"
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).replace(/^ /u, ""))
    }
  }

  if (dataLines.length === 0 || eventName === "heartbeat") {
    return null
  }

  let data: unknown
  try {
    data = JSON.parse(dataLines.join("\n"))
  } catch (error) {
    if (error instanceof SyntaxError) {
      throw new StreamProtocolError()
    }
    throw error
  }

  const eventData: MutableEventData = {}
  if (typeof data === "object" && data !== null && !Array.isArray(data)) {
    Object.assign(eventData, data)
  }
  eventData.type = eventName
  if (eventName === "done" && !("completed" in eventData)) {
    eventData.completed = true
  }
  normalizePersonalEvent(eventName, eventData, identity)

  const parsed = ChatStreamEventSchema.safeParse(eventData)
  if (!parsed.success) {
    throw new StreamProtocolError()
  }

  if (parsed.data.type === "error") {
    return {
      ...parsed.data,
      message: "The response could not be completed. Please try again.",
    }
  }

  return parsed.data
}

export class SseFrameParser {
  #buffer = ""

  constructor(readonly identity: StreamIdentity = {}) {}

  push(text: string): readonly ChatStreamEvent[] {
    this.#buffer += text
    const events: ChatStreamEvent[] = []
    let boundary = nextFrameBoundary(this.#buffer)

    while (boundary !== -1) {
      const frame = this.#buffer.slice(0, boundary)
      this.#buffer = this.#buffer.slice(boundary + frameLengthAt(this.#buffer, boundary))
      const event = parseFrame(frame, this.identity)
      if (event !== null) {
        events.push(event)
      }
      boundary = nextFrameBoundary(this.#buffer)
    }

    return events
  }

  finish(): readonly ChatStreamEvent[] {
    if (this.#buffer.trim() === "") {
      this.#buffer = ""
      return []
    }

    const event = parseFrame(this.#buffer, this.identity)
    this.#buffer = ""
    return event === null ? [] : [event]
  }
}

async function consumeResponse(
  response: Response,
  options: StreamOptions,
  identity: StreamIdentity,
): Promise<void> {
  if (!response.ok) {
    throw apiErrorFromResponse(response)
  }
  if (response.body === null) {
    throw new StreamProtocolError()
  }

  const decoder = new TextDecoder()
  const parser = new SseFrameParser(identity)
  const reader = response.body.getReader()

  try {
    while (true) {
      const read = await reader.read()
      if (read.done) {
        break
      }
      for (const event of parser.push(decoder.decode(read.value, { stream: true }))) {
        options.onEvent(event)
      }
    }
    for (const event of parser.push(decoder.decode())) {
      options.onEvent(event)
    }
    for (const event of parser.finish()) {
      options.onEvent(event)
    }
  } catch (error) {
    if (options.signal.aborted || isAbortError(error)) {
      throw new StreamCancelledError()
    }
    throw error
  } finally {
    reader.releaseLock()
  }
}

async function openStream(
  path: `/api/${string}`,
  init: RequestInit,
  options: StreamOptions,
  identity: StreamIdentity = {},
): Promise<void> {
  let response: Response
  try {
    response = await fetch(path, {
      ...init,
      credentials: "same-origin",
      signal: options.signal,
    })
  } catch (error) {
    if (options.signal.aborted || isAbortError(error)) {
      throw new StreamCancelledError()
    }
    throw error
  }

  await consumeResponse(response, options, identity)
}

export async function streamChat(request: ChatSendRequest, options: StreamOptions): Promise<void> {
  const parsed = ChatSendRequestSchema.safeParse(request)
  if (!parsed.success) {
    throw new StreamProtocolError()
  }
  const csrfHeaders = await csrfHeadersForMutation("/api/personal/chat/send", {
    establish: () =>
      fetch("/api/saas/auth/csrf", {
        credentials: "same-origin",
        signal: options.signal,
      }),
    readToken: browserCsrfToken,
  })

  await openStream(
    "/api/personal/chat/send",
    {
      body: JSON.stringify(parsed.data),
      headers: {
        Accept: "text/event-stream",
        "Content-Type": "application/json",
        ...csrfHeaders,
      },
      method: "POST",
    },
    options,
    {
      ...(parsed.data.message_id === undefined ? {} : { messageId: parsed.data.message_id }),
      ...(parsed.data.session_id === undefined ? {} : { sessionId: parsed.data.session_id }),
    },
  )
}

export function reattachChatStream(sessionId: string, options: StreamOptions): Promise<void> {
  return openStream(
    `/api/personal/chat/sessions/${encodeURIComponent(sessionId)}/stream`,
    { headers: { Accept: "text/event-stream" }, method: "GET" },
    options,
    { sessionId },
  )
}

export function cancelChatStream(
  sessionId: string,
  signal?: AbortSignal,
  client: ApiClient = apiClient,
): Promise<ChatCancelResponse> {
  return client.post(
    `/api/personal/chat/sessions/${encodeURIComponent(sessionId)}/cancel`,
    {},
    ChatCancelResponseSchema,
    signal === undefined ? {} : { signal },
  )
}

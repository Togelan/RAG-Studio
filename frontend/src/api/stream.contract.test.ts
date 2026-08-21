import { afterEach, describe, expect, it, vi } from "vitest"

import { ChatCancelResponseSchema } from "../types/api"
import type { KyHttpClient, KyRequestOptions } from "./client"
import { ApiClient } from "./client"
import { ApiContractError, ApiError, StreamProtocolError } from "./errors"
import { cancelChatStream, reattachChatStream, SseFrameParser, streamChat } from "./stream"

function streamResponse(chunks: readonly string[]): Response {
  const encoder = new TextEncoder()
  const body = new ReadableStream<Uint8Array>({
    start(controller): void {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk))
      }
      controller.close()
    },
  })
  return new Response(body, { headers: { "Content-Type": "text/event-stream" } })
}

function fragmentedStreamResponse(payload: string, boundaries: readonly number[]): Response {
  const encoder = new TextEncoder()
  const bytes = encoder.encode(payload)
  const body = new ReadableStream<Uint8Array>({
    start(controller): void {
      let start = 0
      for (const end of boundaries) {
        controller.enqueue(bytes.slice(start, end))
        start = end
      }
      controller.enqueue(bytes.slice(start))
      controller.close()
    },
  })
  return new Response(body, { headers: { "Content-Type": "text/event-stream" } })
}

function staticKyClient(response: Response, inputs: string[]): KyHttpClient {
  const request = (input: string, _options: KyRequestOptions): Promise<Response> => {
    inputs.push(input)
    return Promise.resolve(response.clone())
  }

  return { delete: request, get: request, patch: request, post: request }
}

describe("SseFrameParser", () => {
  it("parses fragmented UTF-8, CRLF, and multiline payloads while ignoring heartbeats", () => {
    const parser = new SseFrameParser()
    const events = [
      ...parser.push('event: token\r\ndata: {"token":"Пр'),
      ...parser.push('ивет"}\r\n\r\n: heartbeat\n\n'),
      ...parser.push('event: progress\ndata: {"stage":"retrieving"}\ndata: \n\n'),
    ]

    expect(events).toEqual([
      { type: "token", token: "Привет" },
      { type: "progress", stage: "retrieving" },
    ])
  })

  it("rejects malformed or non-public events without exposing their payload", () => {
    const parser = new SseFrameParser()
    expect(() => parser.push("event: token\ndata: {bad}\n\n")).toThrow(StreamProtocolError)
    expect(() => parser.push('event: result\ndata: {"path":"/secret"}\n\n')).toThrow(
      StreamProtocolError,
    )
  })

  it("redacts server-provided stream error text", () => {
    const parser = new SseFrameParser()
    const events = parser.push(
      'event: error\ndata: {"code":"stream_failed","message":"provider /private/path","retryable":true}\n\n',
    )

    expect(events).toEqual([
      {
        code: "stream_failed",
        message: "The response could not be completed. Please try again.",
        retryable: true,
        type: "error",
      },
    ])
  })

  it("accepts the backend replay-buffer terminal sequence without a second protocol error", () => {
    const parser = new SseFrameParser()
    const events = parser.push(
      'event: error\ndata: {"code":"replay_buffer_exhausted","message":"Response exceeded the replay limit.","retryable":true}\n\nevent: done\ndata: {"done":true,"completed":false}\n\n',
    )

    expect(events).toEqual([
      {
        code: "replay_buffer_exhausted",
        message: "The response could not be completed. Please try again.",
        retryable: true,
        type: "error",
      },
      { completed: false, done: true, type: "done" },
    ])
  })
})

describe("stream boundary", () => {
  afterEach(() => vi.unstubAllGlobals())

  it("adds the double-submit CSRF proof when starting a protected chat stream", async () => {
    // Given: the SaaS BFF has established its readable CSRF companion cookie.
    vi.stubGlobal("document", { cookie: "__Host-ragstudio-csrf=chat-proof" })
    const fetchSpy = vi.fn(() => Promise.resolve(streamResponse([])))
    vi.stubGlobal("fetch", fetchSpy)
    const controller = new AbortController()

    // When: Personal Lab starts its primary POST stream.
    await streamChat({ content: "question" }, { onEvent: vi.fn(), signal: controller.signal })

    // Then: the protected endpoint receives the matching proof.
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/chat/send",
      expect.objectContaining({
        headers: expect.objectContaining({ "X-CSRF-Token": "chat-proof" }),
        method: "POST",
      }),
    )
  })

  it("decodes UTF-8 code points split across stream reads", async () => {
    const greeting = "\u041f\u0440\u0438\u0432\u0435\u0442"
    const payload = `event: token\ndata: {"token":"${greeting}"}\n\n`
    const fetchSpy = vi.fn(() => Promise.resolve(fragmentedStreamResponse(payload, [24, 25, 26])))
    vi.stubGlobal("fetch", fetchSpy)
    const controller = new AbortController()
    const tokens: string[] = []

    await streamChat(
      { content: "question" },
      {
        onEvent: (event) => {
          if (event.type === "token") {
            tokens.push(event.token)
          }
        },
        signal: controller.signal,
      },
    )

    expect(tokens).toEqual([greeting])
  })

  it("uses one AbortSignal for POST streaming and emits only parsed public events", async () => {
    const fetchSpy = vi.fn(() =>
      Promise.resolve(
        streamResponse([
          'event: start\ndata: {"protocol":"1","message_id":"assistant-1","session_id":"session-1"}\n\n',
          'event: done\ndata: {"done":true,"message_id":"assistant-1","full_response":"safe","citations":[]}\n\n',
        ]),
      ),
    )
    vi.stubGlobal("fetch", fetchSpy)
    const controller = new AbortController()
    const events: string[] = []

    await streamChat(
      { content: "question", message_id: "message-1", session_id: "session-1" },
      { onEvent: (event) => events.push(event.type), signal: controller.signal },
    )

    expect(events).toEqual(["start", "done"])
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/chat/send",
      expect.objectContaining({
        body: '{"content":"question","session_id":"session-1","message_id":"message-1"}',
        method: "POST",
        signal: controller.signal,
      }),
    )
  })

  it("consumes the real replay-buffer overflow sequence as a terminal stream", async () => {
    const fetchSpy = vi.fn(() =>
      Promise.resolve(
        streamResponse([
          'event: error\ndata: {"code":"replay_buffer_exhausted","message":"Response exceeded the replay limit.","retryable":true}\n\n',
          'event: done\ndata: {"done":true,"completed":false}\n\n',
        ]),
      ),
    )
    vi.stubGlobal("fetch", fetchSpy)
    const controller = new AbortController()
    const events: string[] = []

    await expect(
      streamChat(
        { content: "overflow" },
        { onEvent: (event) => events.push(event.type), signal: controller.signal },
      ),
    ).resolves.toBeUndefined()
    expect(events).toEqual(["error", "done"])
  })

  it("uses an explicit GET reattach endpoint without automatic retry", async () => {
    const fetchSpy = vi.fn(() => Promise.resolve(streamResponse([])))
    vi.stubGlobal("fetch", fetchSpy)
    const controller = new AbortController()

    await reattachChatStream("session/1", { onEvent: vi.fn(), signal: controller.signal })

    expect(fetchSpy).toHaveBeenCalledTimes(1)
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/chat/sessions/session%2F1/stream",
      expect.objectContaining({ method: "GET", signal: controller.signal }),
    )
  })

  it("keeps ky inputs relative, disables mutation retry, and sanitizes HTTP failures", async () => {
    const inputs: string[] = []
    const client = new ApiClient(
      fetch,
      staticKyClient(new Response('{"detail":"/private/provider/path"}', { status: 503 }), inputs),
      () => "csrf-proof",
    )

    await expect(
      client.post("/api/chat/sessions/session-1/cancel", {}, ChatCancelResponseSchema),
    ).rejects.toMatchObject(
      new ApiError(503, "The service is temporarily unavailable. Please try again.", null),
    )
    expect(inputs).toEqual(["/api/chat/sessions/session-1/cancel"])
  })

  it("rejects absolute and cross-origin paths before invoking ky", async () => {
    const inputs: string[] = []
    const client = new ApiClient(
      fetch,
      staticKyClient(new Response('{"status":"stopped","session_id":"session-1"}'), inputs),
      () => "csrf-proof",
    )

    await expect(
      client.get("https://example.com/api/settings", ChatCancelResponseSchema),
    ).rejects.toBeInstanceOf(ApiContractError)
    await expect(
      client.get("//example.com/api/settings", ChatCancelResponseSchema),
    ).rejects.toBeInstanceOf(ApiContractError)
    expect(inputs).toEqual([])
  })

  it("uses the cancellation helper endpoint", async () => {
    const inputs: string[] = []
    const client = new ApiClient(
      fetch,
      staticKyClient(new Response('{"status":"stopped","session_id":"session-1"}'), inputs),
      () => "csrf-proof",
    )

    await expect(cancelChatStream("session-1", undefined, client)).resolves.toEqual({
      status: "stopped",
      session_id: "session-1",
    })
    expect(inputs).toEqual(["/api/chat/sessions/session-1/cancel"])
  })
})

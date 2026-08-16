import { ApiError, StreamCancelledError, StreamProtocolError } from "../../api/errors"
import type { ChatStreamEvent } from "../../types/api"
import {
  errorState,
  type FrameScheduler,
  reduceStreamEvent,
  removeSession,
  replaceSession,
  scheduleFrame,
  updateMessageCount,
  userMessage,
} from "./chat-controller-runtime"
import {
  CHAT_CONTENT_LIMIT,
  type ChatGateway,
  type ChatSnapshot,
  type ChatStreamGateway,
  INITIAL_CHAT_SNAPSHOT,
} from "./model"

type Listener = () => void

export class ChatController {
  readonly #listeners = new Set<Listener>()
  readonly #scheduleFrame: FrameScheduler
  #abortController: AbortController | null = null
  #framePending = false
  #operation = 0
  #pendingTokens = ""
  #snapshot: ChatSnapshot = INITIAL_CHAT_SNAPSHOT
  #terminalSeen = false

  constructor(
    readonly gateway: ChatGateway,
    readonly streams: ChatStreamGateway,
    readonly nextId: () => string,
    schedule: FrameScheduler = scheduleFrame,
  ) {
    this.#scheduleFrame = schedule
  }
  snapshot = (): ChatSnapshot => this.#snapshot
  subscribe = (listener: Listener): (() => void) => {
    this.#listeners.add(listener)
    return (): void => {
      this.#listeners.delete(listener)
    }
  }
  async load(): Promise<void> {
    try {
      this.#set({ ...this.#snapshot, sessions: await this.gateway.listSessions() })
    } catch (error) {
      this.#set({ ...this.#snapshot, stream: errorState(error) })
    }
  }

  async createSession(): Promise<void> {
    await this.#cancelActive(true)
    try {
      const session = await this.gateway.createSession("New Session")
      this.#set({ ...this.#snapshot, sessions: [session, ...this.#snapshot.sessions] })
      await this.selectSession(session.id, false)
    } catch (error) {
      this.#set({ ...this.#snapshot, stream: errorState(error) })
    }
  }

  async selectSession(sessionId: string, reattach = true): Promise<void> {
    this.detach()
    const operation = this.#operation
    this.#set({
      ...this.#snapshot,
      activeSessionId: sessionId,
      messages: [],
      partialResponse: "",
      stream: { kind: "idle" },
    })
    try {
      const messages = await this.gateway.listMessages(sessionId)
      if (!this.#current(operation, sessionId)) return
      this.#set({ ...this.#snapshot, messages })
    } catch (error) {
      if (!this.#current(operation, sessionId)) return
      this.#set({ ...this.#snapshot, stream: errorState(error) })
      return
    }
    if (reattach) await this.reattach()
  }

  async renameSession(sessionId: string, title: string): Promise<void> {
    const cleanTitle = title.trim().slice(0, 200)
    if (!cleanTitle) return
    try {
      const updated = await this.gateway.renameSession(sessionId, cleanTitle)
      const existing = this.#snapshot.sessions.find((session) => session.id === sessionId)
      this.#set({
        ...this.#snapshot,
        sessions: replaceSession(this.#snapshot.sessions, {
          ...updated,
          message_count: existing?.message_count ?? updated.message_count,
        }),
      })
    } catch (error) {
      this.#set({ ...this.#snapshot, stream: errorState(error) })
    }
  }

  async deleteSession(sessionId: string): Promise<void> {
    if (this.#snapshot.activeSessionId === sessionId) await this.#cancelActive(true)
    try {
      await this.gateway.deleteSession(sessionId)
      this.#set(removeSession(this.#snapshot, sessionId))
    } catch (error) {
      this.#set({ ...this.#snapshot, stream: errorState(error) })
    }
  }

  async clearMessages(): Promise<void> {
    const sessionId = this.#snapshot.activeSessionId
    if (sessionId === null) return
    await this.#cancelActive(true)
    try {
      await this.gateway.clearMessages(sessionId)
      this.#set({
        ...this.#snapshot,
        messages: [],
        partialResponse: "",
        sessions: updateMessageCount(this.#snapshot.sessions, sessionId, 0),
        stream: { kind: "idle" },
      })
    } catch (error) {
      this.#set({ ...this.#snapshot, stream: errorState(error) })
    }
  }

  async send(rawContent: string): Promise<void> {
    const sessionId = this.#snapshot.activeSessionId
    const content = rawContent.trim()
    if (sessionId === null || !content || content.length > CHAT_CONTENT_LIMIT) return
    this.detach()
    const operation = this.#operation
    const messageId = this.nextId()
    this.#terminalSeen = false
    try {
      const committed = await this.gateway.commitMessage(sessionId, {
        content,
        message_id: messageId,
      })
      if (!this.#current(operation, sessionId)) return
      this.#set({
        ...this.#snapshot,
        messages: [...this.#snapshot.messages, committed ?? userMessage(content, messageId)],
        sessions: updateMessageCount(
          this.#snapshot.sessions,
          sessionId,
          this.#snapshot.messages.length + 1,
        ),
        stream: { kind: "connecting" },
      })
      await this.#consume(operation, sessionId, (options) =>
        this.streams.send({ content, message_id: messageId, session_id: sessionId }, options),
      )
    } catch (error) {
      this.#handleFailure(error, operation, sessionId)
    }
  }

  async reattach(): Promise<void> {
    const sessionId = this.#snapshot.activeSessionId
    if (sessionId === null) return
    this.detach()
    const operation = this.#operation
    this.#terminalSeen = false
    this.#set({ ...this.#snapshot, stream: { kind: "connecting" } })
    try {
      await this.#consume(operation, sessionId, (options) =>
        this.streams.reattach(sessionId, options),
      )
    } catch (error) {
      if (
        error instanceof ApiError &&
        error.status === 404 &&
        this.#current(operation, sessionId)
      ) {
        this.#set({ ...this.#snapshot, stream: { kind: "idle" } })
        return
      }
      this.#handleFailure(error, operation, sessionId)
    }
  }

  async stop(): Promise<void> {
    const cancellation = this.#cancelActive(true)
    this.#set({ ...this.#snapshot, partialResponse: "", stream: { kind: "cancelled" } })
    await cancellation
  }

  detach(): void {
    this.#operation += 1
    this.#abortController?.abort()
    this.#abortController = null
    this.#pendingTokens = ""
    this.#framePending = false
  }

  async feedback(
    messageId: string,
    value: "positive" | "negative",
    reason?: string,
  ): Promise<void> {
    const sessionId = this.#snapshot.activeSessionId
    if (sessionId === null) return
    await this.gateway.feedback({
      feedback: value,
      message_id: messageId,
      ...(reason ? { reason } : {}),
      session_id: sessionId,
    })
  }

  async #consume(
    operation: number,
    sessionId: string,
    run: (options: {
      readonly onEvent: (event: ChatStreamEvent) => void
      readonly signal: AbortSignal
    }) => Promise<void>,
  ): Promise<void> {
    const abortController = new AbortController()
    this.#abortController = abortController
    await run({
      onEvent: (event) => this.#event(event, operation, sessionId),
      signal: abortController.signal,
    })
    if (this.#current(operation, sessionId) && !this.#terminalSeen) throw new StreamProtocolError()
    if (this.#current(operation, sessionId)) this.#abortController = null
  }

  #event(event: ChatStreamEvent, operation: number, sessionId: string): void {
    if (!this.#current(operation, sessionId)) return
    if (event.type === "token") {
      this.#queueToken(event.token, operation, sessionId)
      return
    }
    const transition = reduceStreamEvent(this.#snapshot, event, sessionId)
    if (transition.terminal) this.#terminalSeen = true
    if (transition.clearPendingTokens) this.#pendingTokens = ""
    if (transition.snapshot !== null) this.#set(transition.snapshot)
  }

  #queueToken(token: string, operation: number, sessionId: string): void {
    this.#pendingTokens += token
    if (this.#framePending) return
    this.#framePending = true
    globalThis.performance?.mark("rag-chat-token-received")
    this.#scheduleFrame(() => {
      this.#framePending = false
      if (!this.#current(operation, sessionId) || !this.#pendingTokens) return
      const next = this.#pendingTokens
      this.#pendingTokens = ""
      this.#set({ ...this.#snapshot, partialResponse: this.#snapshot.partialResponse + next })
      globalThis.performance?.mark("rag-chat-token-painted")
      globalThis.performance?.measure(
        "rag-chat-response-to-dom",
        "rag-chat-token-received",
        "rag-chat-token-painted",
      )
    })
  }

  async #cancelActive(cancelBackend: boolean): Promise<void> {
    const sessionId = this.#snapshot.activeSessionId
    this.detach()
    if (cancelBackend && sessionId !== null) {
      try {
        await this.streams.cancel(sessionId)
      } catch (error) {
        if (!(error instanceof ApiError && error.status === 404)) throw error
      }
    }
  }

  #handleFailure(error: unknown, operation: number, sessionId: string): void {
    if (!this.#current(operation, sessionId) || error instanceof StreamCancelledError) return
    this.#set({ ...this.#snapshot, partialResponse: "", stream: errorState(error) })
  }

  #current(operation: number, sessionId: string): boolean {
    return operation === this.#operation && sessionId === this.#snapshot.activeSessionId
  }

  #set(snapshot: ChatSnapshot): void {
    this.#snapshot = snapshot
    for (const listener of this.#listeners) listener()
  }
}

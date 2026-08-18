import { useEffect, useRef, useState } from "react"

import { Button } from "../../../components/ui/button"
import type { ChatStreamEvent } from "../../../types/api"
import type { SaasLocale } from "../model"
import type {
  TestChatFeedbackInput,
  TestChatGateway,
  TestChatStreamGateway,
  TestSession,
} from "./test-chat-api"
import "./test-chat.css"

type CompletedStreamEvent = Extract<ChatStreamEvent, { readonly completed: true }>
type Citation = CompletedStreamEvent["citations"][number]

type Answer = {
  readonly citations: readonly Citation[]
  readonly messageId: string | null
  readonly text: string
}

type Copy = {
  readonly cancel: string
  readonly cancelled: string
  readonly citation: string
  readonly complete: string
  readonly empty: string
  readonly error: string
  readonly helpful: string
  readonly loading: string
  readonly location: string
  readonly locationUnavailable: string
  readonly message: string
  readonly negative: string
  readonly reattach: string
  readonly reference: string
  readonly send: string
  readonly sending: string
  readonly snippet: string
  readonly snippetUnavailable: string
  readonly start: string
  readonly testTitle: string
}

const copy: Readonly<Record<SaasLocale, Copy>> = {
  en: {
    cancel: "Cancel response",
    cancelled: "Response cancelled.",
    citation: "Citation",
    complete: "Response complete.",
    empty: "Start a private test conversation for this chatbot.",
    error: "The test conversation could not be completed. Please try again.",
    helpful: "Helpful",
    loading: "Loading test conversations…",
    location: "Location",
    locationUnavailable: "Location unavailable",
    message: "Message",
    negative: "Not helpful",
    reattach: "Reattach response",
    reference: "Reference",
    send: "Send",
    sending: "Sending…",
    snippet: "Excerpt",
    snippetUnavailable: "No excerpt is available.",
    start: "Start test conversation",
    testTitle: "Test conversation",
  },
  ru: {
    cancel: "Отменить ответ",
    cancelled: "Ответ отменён.",
    citation: "Источник",
    complete: "Ответ готов.",
    empty: "Начните приватный тестовый диалог с этим чатботом.",
    error: "Не удалось завершить тестовый диалог. Повторите попытку.",
    helpful: "Полезно",
    loading: "Загрузка тестовых диалогов…",
    location: "Расположение",
    locationUnavailable: "Расположение недоступно",
    message: "Сообщение",
    negative: "Не полезно",
    reattach: "Переподключиться к ответу",
    reference: "Идентификатор",
    send: "Отправить",
    sending: "Отправка…",
    snippet: "Фрагмент",
    snippetUnavailable: "Фрагмент недоступен.",
    start: "Начать тестовый диалог",
    testTitle: "Тестовый диалог",
  },
}

function citationLocation(citation: Citation, locale: SaasLocale): string | null {
  if (citation.location !== undefined && citation.location !== "") return citation.location
  if (citation.page === undefined) return null
  return locale === "ru" ? `Страница ${citation.page}` : `Page ${citation.page}`
}

export function TestChatSurface({
  chatbotId,
  gateway,
  locale,
  streamGateway,
  workspaceId,
}: {
  readonly chatbotId: string
  readonly gateway: TestChatGateway
  readonly locale: SaasLocale
  readonly streamGateway: TestChatStreamGateway
  readonly workspaceId: string
}): React.JSX.Element {
  const labels = copy[locale]
  const activeRequest = useRef<AbortController | null>(null)
  const [sessions, setSessions] = useState<readonly TestSession[]>([])
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [streaming, setStreaming] = useState(false)
  const [message, setMessage] = useState("")
  const [answer, setAnswer] = useState<Answer>({ citations: [], messageId: null, text: "" })
  const [notice, setNotice] = useState<"cancelled" | "error" | null>(null)
  const [feedbackPending, setFeedbackPending] = useState(false)

  useEffect(() => {
    let active = true
    void gateway
      .listSessions(workspaceId, chatbotId)
      .then((records) => {
        if (active) setSessions(records)
      })
      .catch(() => {
        if (active) setNotice("error")
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return (): void => {
      active = false
      activeRequest.current?.abort()
    }
  }, [chatbotId, gateway, workspaceId])

  const receiveEvent = (event: ChatStreamEvent): void => {
    if (event.type === "token") {
      setAnswer((current) => ({ ...current, text: `${current.text}${event.token}` }))
      return
    }
    if (event.type === "done" && event.completed) {
      setAnswer({
        citations: event.citations,
        messageId: event.message_id,
        text: event.full_response,
      })
      return
    }
    if (event.type === "error") setNotice("error")
  }

  const createSession = async (): Promise<void> => {
    setCreating(true)
    setNotice(null)
    try {
      const session = await gateway.createSession(workspaceId, chatbotId, {
        title: labels.testTitle,
      })
      setSessions((current) => [session, ...current])
      setSelectedSessionId(session.session_id)
    } catch {
      setNotice("error")
    } finally {
      setCreating(false)
    }
  }

  const runStream = async (
    operation: (controller: AbortController) => Promise<void>,
  ): Promise<void> => {
    const controller = new AbortController()
    activeRequest.current = controller
    setAnswer({ citations: [], messageId: null, text: "" })
    setNotice(null)
    setStreaming(true)
    try {
      await operation(controller)
    } catch {
      setNotice(controller.signal.aborted ? "cancelled" : "error")
    } finally {
      if (activeRequest.current === controller) activeRequest.current = null
      setStreaming(false)
    }
  }

  const sendMessage = (event: React.FormEvent<HTMLFormElement>): void => {
    event.preventDefault()
    const content = message.trim()
    if (selectedSessionId === null || content === "" || streaming) return
    setMessage("")
    void runStream((controller) =>
      streamGateway.send(
        workspaceId,
        chatbotId,
        selectedSessionId,
        { content, locale },
        { onEvent: receiveEvent, signal: controller.signal },
      ),
    )
  }

  const reattach = (): void => {
    if (selectedSessionId === null || streaming) return
    void runStream((controller) =>
      streamGateway.reattach(workspaceId, chatbotId, selectedSessionId, {
        onEvent: receiveEvent,
        signal: controller.signal,
      }),
    )
  }

  const cancel = async (): Promise<void> => {
    if (selectedSessionId === null) return
    activeRequest.current?.abort()
    setNotice("cancelled")
    setStreaming(false)
    try {
      await streamGateway.cancel(workspaceId, chatbotId, selectedSessionId)
    } catch {
      setNotice("error")
    }
  }

  const storeFeedback = async (input: TestChatFeedbackInput): Promise<void> => {
    if (selectedSessionId === null) return
    setFeedbackPending(true)
    try {
      await gateway.feedback(workspaceId, chatbotId, selectedSessionId, input)
    } catch {
      setNotice("error")
    } finally {
      setFeedbackPending(false)
    }
  }

  return (
    <section className="rs-test-chat">
      {loading ? <p aria-busy="true">{labels.loading}</p> : null}
      {!loading ? (
        <div className="rs-test-chat__sessions">
          <Button
            disabled={creating || streaming}
            onClick={() => void createSession()}
            type="button"
          >
            {labels.start}
          </Button>
          {sessions.map((session) => (
            <Button
              aria-pressed={selectedSessionId === session.session_id}
              disabled={streaming}
              key={session.session_id}
              onClick={() => setSelectedSessionId(session.session_id)}
              type="button"
            >
              {session.title}
            </Button>
          ))}
        </div>
      ) : null}
      {!loading && sessions.length === 0 && selectedSessionId === null ? (
        <p>{labels.empty}</p>
      ) : null}
      {notice !== null ? (
        <p role="status">{notice === "cancelled" ? labels.cancelled : labels.error}</p>
      ) : null}
      {selectedSessionId !== null ? (
        <>
          {answer.text === "" ? (
            <Button disabled={streaming} onClick={reattach} variant="secondary">
              {labels.reattach}
            </Button>
          ) : null}
          {answer.text !== "" ? (
            <article>
              <p>{answer.text}</p>
              {answer.messageId !== null ? <p role="status">{labels.complete}</p> : null}
              {answer.citations.length > 0 ? (
                <ul className="rs-test-chat__citations">
                  {answer.citations.map((citation, index) => (
                    <li key={`${citation.filename ?? "source"}-${citation.page ?? index}`}>
                      <details>
                        <summary>
                          {labels.citation} {index + 1}: {citation.filename ?? labels.citation}
                        </summary>
                        <dl>
                          <div>
                            <dt>{labels.reference}</dt>
                            <dd>{`${answer.messageId ?? "response"}-${index + 1}`}</dd>
                          </div>
                          <div>
                            <dt>{labels.location}</dt>
                            <dd>
                              {citationLocation(citation, locale) ?? labels.locationUnavailable}
                            </dd>
                          </div>
                          <div>
                            <dt>{labels.snippet}</dt>
                            <dd>{citation.content ?? labels.snippetUnavailable}</dd>
                          </div>
                        </dl>
                      </details>
                    </li>
                  ))}
                </ul>
              ) : null}
              {answer.messageId !== null ? (
                <div className="rs-test-chat__feedback">
                  <Button
                    disabled={feedbackPending}
                    onClick={() =>
                      void storeFeedback({
                        message_id: answer.messageId ?? "",
                        feedback: "positive",
                      })
                    }
                    type="button"
                  >
                    {labels.helpful}
                  </Button>
                  <Button
                    disabled={feedbackPending}
                    onClick={() =>
                      void storeFeedback({
                        message_id: answer.messageId ?? "",
                        feedback: "negative",
                      })
                    }
                    type="button"
                  >
                    {labels.negative}
                  </Button>
                </div>
              ) : null}
            </article>
          ) : null}
          <form onSubmit={sendMessage}>
            <label htmlFor={`test-chat-message-${chatbotId}`}>{labels.message}</label>
            <textarea
              disabled={streaming}
              id={`test-chat-message-${chatbotId}`}
              maxLength={10_000}
              onChange={(event) => setMessage(event.currentTarget.value)}
              required
              value={message}
            />
            {streaming ? (
              <Button onClick={() => void cancel()} variant="danger">
                {labels.cancel}
              </Button>
            ) : (
              <Button disabled={message.trim() === ""} type="submit">
                {labels.send}
              </Button>
            )}
            {streaming ? <span aria-live="polite">{labels.sending}</span> : null}
          </form>
        </>
      ) : null}
    </section>
  )
}

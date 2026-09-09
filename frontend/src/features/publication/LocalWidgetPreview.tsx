import { Send } from "lucide-react"
import { type FormEvent, useEffect, useState, useSyncExternalStore } from "react"

import { useLocaleContext } from "../../app/locale-provider"
import { Button } from "../../components/ui/button"
import { Input } from "../../components/ui/input"
import { createChatGateway, defaultChatStreamGateway } from "../chat/chat-api"
import { ChatController } from "../chat/chat-controller"
import type { ChatGateway, ChatStreamGateway } from "../chat/model"

function randomId(): string {
  return globalThis.crypto.randomUUID()
}

export function LocalWidgetPreview({
  gateway,
  streamGateway = defaultChatStreamGateway,
}: {
  readonly gateway?: ChatGateway | undefined
  readonly streamGateway?: ChatStreamGateway | undefined
}): React.JSX.Element {
  const { t } = useLocaleContext()
  const [controller] = useState(
    () => new ChatController(gateway ?? createChatGateway(), streamGateway, randomId),
  )
  const snapshot = useSyncExternalStore(
    controller.subscribe,
    controller.snapshot,
    controller.snapshot,
  )
  const [input, setInput] = useState("")

  useEffect(() => {
    let active = true
    void controller.load().then(async () => {
      if (!active) return
      const first = controller.snapshot().sessions[0]
      if (first === undefined) await controller.createSession()
      else await controller.selectSession(first.id, false)
    })
    return (): void => {
      active = false
      controller.detach()
    }
  }, [controller])

  const submit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault()
    const content = input.trim()
    if (content === "" || snapshot.activeSessionId === null) return
    setInput("")
    void controller.send(content)
  }

  const busy = snapshot.stream.kind === "connecting" || snapshot.stream.kind === "streaming"

  return (
    <section aria-labelledby="local-widget-preview-title" className="rs-local-widget">
      <header className="rs-local-widget__header">
        <div>
          <p>{t("publication_local_preview_badge")}</p>
          <h3 id="local-widget-preview-title">{t("publication_local_preview_title")}</h3>
        </div>
        <span>{t("publication_local_preview_private")}</span>
      </header>
      <div
        aria-label={t("publication_local_preview_messages")}
        className="rs-local-widget__messages"
        role="log"
      >
        {snapshot.messages.length === 0 && snapshot.partialResponse === "" ? (
          <p className="rs-local-widget__empty">{t("publication_local_preview_empty")}</p>
        ) : null}
        {snapshot.messages.map((message) => (
          <article
            className={`rs-local-widget__message rs-local-widget__message--${message.role}`}
            key={message.id}
          >
            <strong>
              {message.role === "user"
                ? t("publication_local_preview_you")
                : t("publication_local_preview_assistant")}
            </strong>
            <p>{message.content}</p>
            {message.citations?.map((citation) => (
              <span
                className="rs-local-widget__citation"
                key={`${message.id}-${citation.filename}-${citation.source}-${citation.location}-${citation.page}`}
              >
                {citation.filename ?? citation.source ?? t("chat_source")}
                {citation.location === undefined ? "" : ` · ${citation.location}`}
              </span>
            ))}
          </article>
        ))}
        {snapshot.partialResponse === "" ? null : (
          <article className="rs-local-widget__message rs-local-widget__message--assistant">
            <strong>{t("publication_local_preview_assistant")}</strong>
            <p>{snapshot.partialResponse}</p>
          </article>
        )}
      </div>
      {snapshot.stream.kind === "error" ? (
        <p className="rs-local-widget__error" role="alert">
          {t("publication_local_preview_failed")}
        </p>
      ) : null}
      <form className="rs-local-widget__composer" onSubmit={submit}>
        <label className="rs-visually-hidden" htmlFor="local-widget-message">
          {t("publication_local_preview_input")}
        </label>
        <Input
          disabled={snapshot.activeSessionId === null || busy}
          id="local-widget-message"
          onChange={(event) => setInput(event.target.value)}
          placeholder={t("publication_local_preview_placeholder")}
          value={input}
        />
        <Button
          aria-label={t("publication_local_preview_send")}
          disabled={snapshot.activeSessionId === null || busy || input.trim() === ""}
          size="icon"
          type="submit"
        >
          <Send aria-hidden="true" size={17} />
        </Button>
      </form>
    </section>
  )
}

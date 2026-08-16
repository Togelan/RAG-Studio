import { Check, Clipboard, FileText, ThumbsDown, ThumbsUp } from "lucide-react"
import { useState } from "react"

import { Button } from "../../components/ui/button"
import { Input } from "../../components/ui/input"
import type { ChatMessage, Citation } from "./model"

function citationLabel(
  citation: Citation,
  index: number,
  locationUnavailable: string,
  pageLabel: string,
  sourceLabel: string,
): string {
  const source = citation.filename ?? citation.source ?? `${sourceLabel} ${index + 1}`
  const location =
    citation.location ??
    (citation.page === undefined ? locationUnavailable : `${pageLabel} ${citation.page}`)
  return `${source} · ${location}`
}

function CitationDetails({
  citation,
  copy,
  index,
}: {
  readonly citation: Citation
  readonly copy: {
    readonly inspectSource: string
    readonly locationUnavailable: string
    readonly page: string
    readonly snippetUnavailable: string
    readonly source: string
  }
  readonly index: number
}): React.JSX.Element {
  const identifier = `${copy.source} ${index + 1}`
  const title = citation.filename ?? citation.source ?? identifier
  const location =
    citation.location ??
    (citation.page === undefined ? copy.locationUnavailable : `${copy.page} ${citation.page}`)

  return (
    <details className="rs-chat__citation">
      <summary aria-label={`${copy.inspectSource} ${index + 1}`}>
        <FileText aria-hidden="true" size={15} />
        <span className="rs-chat__citation-identifier">{identifier}</span>
        <span className="rs-chat__citation-title">{title}</span>
        <span className="rs-chat__citation-location">{location}</span>
      </summary>
      <p>{citation.content ?? copy.snippetUnavailable}</p>
    </details>
  )
}

function AssistantActions({
  copy,
  message,
  onFeedback,
}: {
  readonly copy: {
    readonly copied: string
    readonly copy: string
    readonly dislike: string
    readonly feedbackReason: string
    readonly helpful: string
    readonly thanks: string
  }
  readonly message: ChatMessage
  readonly onFeedback: (
    messageId: string,
    value: "positive" | "negative",
    reason?: string,
  ) => Promise<void>
}): React.JSX.Element {
  const [copied, setCopied] = useState(false)
  const [feedback, setFeedback] = useState<"positive" | "negative" | null>(null)
  const [reason, setReason] = useState("")

  const submit = async (value: "positive" | "negative", detail?: string): Promise<void> => {
    await onFeedback(message.id, value, detail)
    setFeedback(value)
  }

  return (
    <div className="rs-chat__message-actions">
      <Button
        aria-label={copy.copy}
        className="rs-chat__copy-answer"
        onClick={() => {
          void navigator.clipboard.writeText(message.content).then(() => setCopied(true))
        }}
        size="compact"
        variant="secondary"
      >
        {copied ? (
          <Check aria-hidden="true" size={15} />
        ) : (
          <Clipboard aria-hidden="true" size={15} />
        )}
        {copied ? copy.copied : copy.copy}
      </Button>
      <Button
        aria-label={copy.helpful}
        onClick={() => void submit("positive")}
        size="icon"
        variant="secondary"
      >
        <ThumbsUp aria-hidden="true" size={15} />
      </Button>
      <Button
        aria-label={copy.dislike}
        onClick={() => setFeedback("negative")}
        size="icon"
        variant="secondary"
      >
        <ThumbsDown aria-hidden="true" size={15} />
      </Button>
      {feedback === "negative" ? (
        <form
          className="rs-chat__feedback"
          onSubmit={(event) => {
            event.preventDefault()
            void submit("negative", reason.trim() || undefined)
          }}
        >
          <Input
            aria-label={copy.feedbackReason}
            maxLength={1000}
            onChange={(event) => setReason(event.currentTarget.value)}
            placeholder={copy.feedbackReason}
            value={reason}
          />
          <Button size="compact" type="submit">
            {copy.dislike}
          </Button>
        </form>
      ) : null}
      {feedback !== null && feedback !== "negative" ? (
        <span role="status">{copy.thanks}</span>
      ) : null}
    </div>
  )
}

export function MessageList({
  copy,
  messages,
  onFeedback,
  partialResponse,
}: {
  readonly copy: {
    readonly assistant: string
    readonly copied: string
    readonly copy: string
    readonly dislike: string
    readonly emptyBody: string
    readonly emptyTitle: string
    readonly feedbackReason: string
    readonly helpful: string
    readonly inspectSource: string
    readonly locationUnavailable: string
    readonly page: string
    readonly source: string
    readonly snippetUnavailable: string
    readonly sources: string
    readonly thanks: string
    readonly you: string
  }
  readonly messages: readonly ChatMessage[]
  readonly onFeedback: (
    messageId: string,
    value: "positive" | "negative",
    reason?: string,
  ) => Promise<void>
  readonly partialResponse: string
}): React.JSX.Element {
  if (messages.length === 0 && !partialResponse) {
    return (
      <div className="rs-chat__empty">
        <span aria-hidden="true" className="rs-chat__empty-mark">
          R
        </span>
        <h2>{copy.emptyTitle}</h2>
        <p>{copy.emptyBody}</p>
      </div>
    )
  }

  return (
    <div className="rs-chat__message-stack">
      {messages.map((message) => (
        <article className={`rs-chat__message rs-chat__message--${message.role}`} key={message.id}>
          <p className="rs-chat__speaker">{message.role === "user" ? copy.you : copy.assistant}</p>
          <p className="rs-chat__content">{message.content}</p>
          {message.role === "assistant" ? (
            <>
              {message.citations && message.citations.length > 0 ? (
                <section aria-label={copy.sources} className="rs-chat__citations">
                  <h3>{copy.sources}</h3>
                  <div className="rs-chat__citation-list">
                    {message.citations.map((citation, index) => (
                      <CitationDetails
                        citation={citation}
                        copy={copy}
                        index={index}
                        key={`${message.id}-${citationLabel(citation, index, copy.locationUnavailable, copy.page, copy.source)}`}
                      />
                    ))}
                  </div>
                </section>
              ) : null}
              <AssistantActions copy={copy} message={message} onFeedback={onFeedback} />
            </>
          ) : null}
        </article>
      ))}
      {partialResponse ? (
        <article className="rs-chat__message rs-chat__message--assistant rs-chat__message--streaming">
          <p className="rs-chat__speaker">{copy.assistant}</p>
          <p className="rs-chat__content">{partialResponse}</p>
        </article>
      ) : null}
    </div>
  )
}

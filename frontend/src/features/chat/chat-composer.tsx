import { RotateCcw, Send, Square } from "lucide-react"

import { Button } from "../../components/ui/button"
import { Textarea } from "../../components/ui/textarea"
import { CHAT_CONTENT_LIMIT, type StreamState } from "./model"

export function ChatComposer({
  active,
  copy,
  onChange,
  onRegenerate,
  onSend,
  onStop,
  stream,
  value,
}: {
  readonly active: boolean
  readonly copy: {
    readonly composerHint: string
    readonly message: string
    readonly regenerate: string
    readonly send: string
    readonly stop: string
  }
  readonly onChange: (value: string) => void
  readonly onRegenerate: () => void
  readonly onSend: () => void
  readonly onStop: () => void
  readonly stream: StreamState
  readonly value: string
}): React.JSX.Element {
  const streaming = stream.kind === "connecting" || stream.kind === "streaming"
  const valid = active && value.trim().length > 0 && value.length <= CHAT_CONTENT_LIMIT
  return (
    <div className="rs-chat__composer-wrap">
      <div className="rs-chat__composer">
        <Textarea
          aria-label={copy.message}
          className="rs-chat__composer-input"
          disabled={!active || streaming}
          maxLength={CHAT_CONTENT_LIMIT}
          onChange={(event) => onChange(event.currentTarget.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault()
              if (valid) onSend()
            }
          }}
          rows={2}
          value={value}
        />
        {streaming ? (
          <Button aria-label={copy.stop} onClick={onStop} size="icon" variant="danger">
            <Square aria-hidden="true" size={16} />
          </Button>
        ) : (
          <Button
            aria-label={copy.send}
            disabled={!valid}
            onClick={onSend}
            size="icon"
            variant="ai"
          >
            <Send aria-hidden="true" size={18} />
          </Button>
        )}
      </div>
      <div className="rs-chat__composer-meta">
        <span>{copy.composerHint}</span>
        <span>
          {value.length.toLocaleString()} / {CHAT_CONTENT_LIMIT.toLocaleString()}
        </span>
        <Button
          aria-label={copy.regenerate}
          className="rs-chat__regenerate"
          disabled={!active || streaming}
          onClick={onRegenerate}
          size="compact"
          variant="secondary"
        >
          <RotateCcw aria-hidden="true" size={15} />
          {copy.regenerate}
        </Button>
      </div>
    </div>
  )
}

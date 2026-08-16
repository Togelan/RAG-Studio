import { MessageSquarePlus, Pencil, Trash2 } from "lucide-react"
import { useState } from "react"

import { Button } from "../../components/ui/button"
import { Input } from "../../components/ui/input"
import type { Session } from "./model"

export function SessionSidebar({
  activeSessionId,
  copy,
  messageCount,
  onCreate,
  onDelete,
  onRename,
  onSelect,
  sessions,
}: {
  readonly activeSessionId: string | null
  readonly copy: {
    readonly delete: string
    readonly newChat: string
    readonly noSessions: string
    readonly rename: string
    readonly sessions: string
  }
  readonly messageCount: (count: number) => string
  readonly onCreate: () => void
  readonly onDelete: (sessionId: string) => void
  readonly onRename: (sessionId: string, title: string) => void
  readonly onSelect: (sessionId: string) => void
  readonly sessions: readonly Session[]
}): React.JSX.Element {
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [title, setTitle] = useState("")

  return (
    <aside aria-label={copy.sessions} className="rs-chat__sidebar">
      <Button className="rs-chat__new" onClick={onCreate} variant="secondary">
        <MessageSquarePlus aria-hidden="true" size={18} />
        {copy.newChat}
      </Button>
      <ul aria-label={copy.sessions} className="rs-chat__sessions">
        {sessions.length === 0 ? (
          <li className="rs-chat__session-empty">{copy.noSessions}</li>
        ) : null}
        {sessions.map((session) => (
          <li
            className={`rs-chat__session-row${activeSessionId === session.id ? " rs-chat__session-row--active" : ""}`}
            key={session.id}
          >
            {renamingId === session.id ? (
              <form
                className="rs-chat__rename"
                onSubmit={(event) => {
                  event.preventDefault()
                  onRename(session.id, title)
                  setRenamingId(null)
                }}
              >
                <Input
                  aria-label={copy.rename}
                  autoFocus
                  maxLength={200}
                  onChange={(event) => setTitle(event.currentTarget.value)}
                  value={title}
                />
                <Button size="compact" type="submit">
                  {copy.rename}
                </Button>
              </form>
            ) : (
              <button
                aria-label={session.title || copy.newChat}
                aria-current={activeSessionId === session.id ? "page" : undefined}
                className="rs-chat__session"
                onClick={() => onSelect(session.id)}
                type="button"
              >
                <span>{session.title || copy.newChat}</span>
                <span
                  aria-hidden="true"
                  className="rs-chat__count"
                  title={messageCount(session.message_count)}
                >
                  {session.message_count}
                </span>
              </button>
            )}
            <div className="rs-chat__session-actions">
              <Button
                aria-label={`${copy.rename}: ${session.title}`}
                onClick={() => {
                  setTitle(session.title)
                  setRenamingId(session.id)
                }}
                size="icon"
                variant="secondary"
              >
                <Pencil aria-hidden="true" size={16} />
              </Button>
              <Button
                aria-label={`${copy.delete}: ${session.title}`}
                onClick={() => onDelete(session.id)}
                size="icon"
                variant="secondary"
              >
                <Trash2 aria-hidden="true" size={16} />
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </aside>
  )
}

import { Menu, Trash2 } from "lucide-react"
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react"

import { useLocaleContext } from "../../app/locale-provider"
import { Button } from "../../components/ui/button"
import { Drawer, DrawerContent, DrawerTitle, DrawerTrigger } from "../../components/ui/drawer"
import { createChatGateway, defaultChatStreamGateway } from "./chat-api"
import { ChatComposer } from "./chat-composer"
import { ChatController } from "./chat-controller"
import { chatCopy } from "./chat-copy"
import "./chat-page.css"
import { MessageList } from "./message-list"
import { ACTIVE_SESSION_STORAGE_KEY, type ChatGateway, type ChatStreamGateway } from "./model"
import { SessionSidebar } from "./session-sidebar"

const DEFAULT_SESSION_TITLE = "New Session"

function randomId(): string {
  return globalThis.crypto.randomUUID()
}

function storedSessionId(): string | null {
  try {
    return globalThis.localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY)
  } catch (error) {
    if (error instanceof DOMException) return null
    throw error
  }
}

function rememberSessionId(sessionId: string | null): void {
  try {
    if (sessionId === null) globalThis.localStorage.removeItem(ACTIVE_SESSION_STORAGE_KEY)
    else globalThis.localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, sessionId)
  } catch (error) {
    if (!(error instanceof DOMException)) throw error
  }
}

export function ChatPage({
  gateway,
  streamGateway = defaultChatStreamGateway,
}: {
  readonly gateway?: ChatGateway
  readonly streamGateway?: ChatStreamGateway
}): React.JSX.Element {
  const { format, t } = useLocaleContext()
  const copy = chatCopy(t)
  const [controller] = useState(
    () => new ChatController(gateway ?? createChatGateway(), streamGateway, randomId),
  )
  const snapshot = useSyncExternalStore(
    controller.subscribe,
    controller.snapshot,
    controller.snapshot,
  )
  const [composer, setComposer] = useState("")
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const scrollArea = useRef<HTMLDivElement>(null)
  const shouldAutoScroll = useRef(true)
  const scrollRevision = snapshot.messages.length + snapshot.partialResponse.length

  useEffect(() => {
    let active = true
    void controller.load().then(async () => {
      if (!active) return
      const sessions = controller.snapshot().sessions
      const remembered = storedSessionId()
      const selected = sessions.find((session) => session.id === remembered) ?? sessions[0]
      if (selected !== undefined) await controller.selectSession(selected.id, true)
    })
    const pagehide = (): void => controller.detach()
    globalThis.addEventListener("pagehide", pagehide)
    return (): void => {
      active = false
      globalThis.removeEventListener("pagehide", pagehide)
      controller.detach()
    }
  }, [controller])

  useEffect(() => rememberSessionId(snapshot.activeSessionId), [snapshot.activeSessionId])

  useEffect(() => {
    if (!shouldAutoScroll.current) return
    const element = scrollArea.current
    if (element !== null && typeof element.scrollTo === "function") {
      element.setAttribute("data-message-revision", String(scrollRevision))
      element.scrollTo({ behavior: "smooth", top: element.scrollHeight })
    }
  }, [scrollRevision])

  const lastUserContent = useMemo(
    () =>
      [...snapshot.messages].reverse().find((message) => message.role === "user")?.content ?? "",
    [snapshot.messages],
  )
  const visibleSessions = useMemo(
    () =>
      snapshot.sessions.map((session) =>
        session.title === DEFAULT_SESSION_TITLE ? { ...session, title: copy.newSession } : session,
      ),
    [copy.newSession, snapshot.sessions],
  )

  const send = (): void => {
    const content = composer
    setComposer("")
    void controller.send(content)
  }

  return (
    <section aria-label={t("nav_chat")} className="rs-chat">
      <header className="rs-chat__header">
        <p className="rs-page__subtitle">{t("chat_subtitle")}</p>
        <Drawer onOpenChange={setSidebarOpen} open={sidebarOpen}>
          <DrawerTrigger asChild>
            <Button
              aria-label={t("aria_toggle_sidebar")}
              className="rs-chat__sidebar-toggle"
              size="icon"
              variant="secondary"
            >
              <Menu aria-hidden="true" size={18} />
            </Button>
          </DrawerTrigger>
          <DrawerContent className="rs-chat__session-drawer">
            <DrawerTitle className="rs-visually-hidden">{copy.sessions}</DrawerTitle>
            <SessionSidebar
              activeSessionId={snapshot.activeSessionId}
              copy={copy}
              onCreate={() => {
                setSidebarOpen(false)
                void controller.createSession()
              }}
              onDelete={(sessionId) => {
                if (globalThis.confirm(t("chat_delete_confirm"))) {
                  setSidebarOpen(false)
                  void controller.deleteSession(sessionId)
                }
              }}
              onRename={(sessionId, title) => void controller.renameSession(sessionId, title)}
              onSelect={(sessionId) => {
                setSidebarOpen(false)
                void controller.selectSession(sessionId, true)
              }}
              messageCount={(count) => format("chat_session_message_count", { count })}
              sessions={visibleSessions}
            />
          </DrawerContent>
        </Drawer>
      </header>

      <div className="rs-chat__workspace">
        <div className="rs-chat__desktop-sidebar">
          <SessionSidebar
            activeSessionId={snapshot.activeSessionId}
            copy={copy}
            onCreate={() => void controller.createSession()}
            onDelete={(sessionId) => {
              if (globalThis.confirm(t("chat_delete_confirm")))
                void controller.deleteSession(sessionId)
            }}
            onRename={(sessionId, title) => void controller.renameSession(sessionId, title)}
            onSelect={(sessionId) => void controller.selectSession(sessionId, true)}
            messageCount={(count) => format("chat_session_message_count", { count })}
            sessions={visibleSessions}
          />
        </div>
        <main className="rs-chat__conversation">
          <div className="rs-chat__conversation-bar">
            <div>
              <p className="rs-chat__conversation-label">{copy.history}</p>
              <strong>
                {visibleSessions.find((session) => session.id === snapshot.activeSessionId)
                  ?.title ?? copy.newChat}
              </strong>
            </div>
            <Button
              aria-label={copy.clear}
              disabled={snapshot.activeSessionId === null || snapshot.messages.length === 0}
              onClick={() => {
                if (globalThis.confirm(t("chat_clear_confirm"))) void controller.clearMessages()
              }}
              size="icon"
              variant="secondary"
            >
              <Trash2 aria-hidden="true" size={17} />
            </Button>
          </div>
          <div
            aria-label={t("aria_chat_messages")}
            className="rs-chat__messages"
            onScroll={(event) => {
              const element = event.currentTarget
              shouldAutoScroll.current =
                element.scrollHeight - element.scrollTop - element.clientHeight < 80
            }}
            ref={scrollArea}
            role="log"
            aria-live="off"
          >
            <MessageList
              copy={copy}
              messages={snapshot.messages}
              onFeedback={(messageId, value, reason) =>
                controller.feedback(messageId, value, reason)
              }
              partialResponse={snapshot.partialResponse}
            />
          </div>
          {snapshot.stream.kind === "streaming" ? (
            <p className="rs-chat__stream-status" role="status">
              {snapshot.stream.stage}
            </p>
          ) : null}
          {snapshot.stream.kind === "cancelled" ? (
            <p className="rs-chat__stream-status" role="status">
              {t("chat_stream_cancelled")}
            </p>
          ) : null}
          {snapshot.stream.kind === "completed" ? (
            <p className="rs-chat__stream-status" role="status">
              {copy.responseComplete}
            </p>
          ) : null}
          {snapshot.stream.kind === "error" ? (
            <p className="rs-chat__error" role="alert">
              {snapshot.stream.messageKey === undefined
                ? snapshot.stream.message
                : t(snapshot.stream.messageKey)}
              {snapshot.stream.retryAfterSeconds === null
                ? ""
                : ` ${format("chat_retry_after", {
                    seconds: snapshot.stream.retryAfterSeconds,
                  })}`}
            </p>
          ) : null}
          <ChatComposer
            active={snapshot.activeSessionId !== null}
            copy={copy}
            onChange={setComposer}
            onRegenerate={() => void controller.send(lastUserContent)}
            onSend={send}
            onStop={() => void controller.stop()}
            stream={snapshot.stream}
            value={composer}
          />
        </main>
      </div>
    </section>
  )
}

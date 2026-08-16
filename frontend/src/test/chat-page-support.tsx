import { render } from "@testing-library/react"
import { vi } from "vitest"
import enLocale from "../../../src/api/locales/en.json"
import ruLocale from "../../../src/api/locales/ru.json"
import { LocaleProvider } from "../app/locale-provider"
import { ChatPage } from "../features/chat/ChatPage"
import type {
  ChatGateway,
  ChatMessage,
  ChatStreamGateway,
  FeedbackInput,
  FeedbackResponse,
  MessageCommitInput,
  Session,
  SessionMutationResponse,
} from "../features/chat/model"
import type { Locale, TranslationKey } from "../i18n/locale-inventory"
import { createLocaleRuntime } from "../i18n/locale-runtime"

export const CHAT_SESSION: Session = {
  created_at: "2026-08-15T00:00:00Z",
  id: "session-a",
  message_count: 0,
  title: "Research",
}

export function renderChat(
  streams: ChatStreamGateway,
  locale: Locale = "en",
  sessions: readonly Session[] = [CHAT_SESSION],
  createSession: ChatGateway["createSession"] = vi.fn(async () => CHAT_SESSION),
): void {
  const authoritativeTranslations = locale === "ru" ? ruLocale : enLocale
  const translations = new Map<TranslationKey, string>(
    Object.entries(authoritativeTranslations) as readonly [TranslationKey, string][],
  )
  const runtime = createLocaleRuntime({
    gateway: {
      setLocale: vi.fn(async (requested) => ({
        locale: requested,
        translations: requested === "ru" ? ruLocale : enLocale,
      })),
    },
    initialLocale: locale,
    initialTranslations: translations,
  })
  const mutation = async (
    status: SessionMutationResponse["status"],
  ): Promise<SessionMutationResponse> => ({ session_id: CHAT_SESSION.id, status })
  const gateway: ChatGateway = {
    cancel: vi.fn(async () => mutation("stopped")),
    clearMessages: vi.fn(async () => mutation("cleared")),
    commitMessage: vi.fn(
      async (_id: string, input: MessageCommitInput): Promise<ChatMessage> => ({
        content: input.content,
        created_at: "",
        id: input.message_id,
        role: "user",
      }),
    ),
    createSession,
    deleteSession: vi.fn(async () => mutation("deleted")),
    feedback: vi.fn(
      async (input: FeedbackInput): Promise<FeedbackResponse> => ({
        feedback: input.feedback,
        status: "saved",
      }),
    ),
    listMessages: vi.fn(async () => []),
    listSessions: vi.fn(async () => sessions),
    renameSession: vi.fn(async (_id, title) => ({ ...CHAT_SESSION, title })),
  }
  render(
    <LocaleProvider runtime={runtime}>
      <ChatPage gateway={gateway} streamGateway={streams} />
    </LocaleProvider>,
  )
}

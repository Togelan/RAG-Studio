import type { TranslationKey } from "../../i18n/locale-inventory"

type ChatCopy = {
  readonly assistant: string
  readonly clear: string
  readonly composerHint: string
  readonly copied: string
  readonly copy: string
  readonly delete: string
  readonly dislike: string
  readonly emptyBody: string
  readonly emptyTitle: string
  readonly feedbackReason: string
  readonly helpful: string
  readonly history: string
  readonly inspectSource: string
  readonly loading: string
  readonly locationUnavailable: string
  readonly message: string
  readonly newChat: string
  readonly newSession: string
  readonly noSessions: string
  readonly page: string
  readonly regenerate: string
  readonly rename: string
  readonly responseComplete: string
  readonly send: string
  readonly sessions: string
  readonly snippetUnavailable: string
  readonly source: string
  readonly sources: string
  readonly stop: string
  readonly thanks: string
  readonly title: string
  readonly you: string
}

const CHAT_COPY_KEYS = {
  assistant: "chat_assistant",
  clear: "aria_clear_chat",
  composerHint: "chat_composer_hint",
  copied: "chat_copied",
  copy: "chat_copy_answer",
  delete: "chat_context_menu_delete",
  dislike: "chat_not_helpful",
  emptyBody: "chat_empty_subtitle",
  emptyTitle: "chat_empty_title",
  feedbackReason: "chat_feedback_reason",
  helpful: "chat_helpful",
  history: "chat_history",
  inspectSource: "chat_inspect_source",
  loading: "chat_loading",
  locationUnavailable: "chat_location_unavailable",
  message: "chat_message_input_label",
  newChat: "chat_new_chat",
  newSession: "chat_new_session",
  noSessions: "chat_no_sessions",
  page: "chat_page",
  regenerate: "aria_regenerate",
  rename: "chat_context_menu_rename",
  responseComplete: "chat_response_complete",
  send: "aria_send_message",
  sessions: "aria_chat_sessions",
  snippetUnavailable: "chat_snippet_unavailable",
  source: "chat_source",
  sources: "chat_sources",
  stop: "aria_stop_generation",
  thanks: "chat_feedback_thanks",
  title: "chat_feature_title",
  you: "chat_you",
} as const satisfies Readonly<Record<keyof ChatCopy, TranslationKey>>

export function chatCopy(translate: (key: TranslationKey) => string): ChatCopy {
  return {
    assistant: translate(CHAT_COPY_KEYS.assistant),
    clear: translate(CHAT_COPY_KEYS.clear),
    composerHint: translate(CHAT_COPY_KEYS.composerHint),
    copied: translate(CHAT_COPY_KEYS.copied),
    copy: translate(CHAT_COPY_KEYS.copy),
    delete: translate(CHAT_COPY_KEYS.delete),
    dislike: translate(CHAT_COPY_KEYS.dislike),
    emptyBody: translate(CHAT_COPY_KEYS.emptyBody),
    emptyTitle: translate(CHAT_COPY_KEYS.emptyTitle),
    feedbackReason: translate(CHAT_COPY_KEYS.feedbackReason),
    helpful: translate(CHAT_COPY_KEYS.helpful),
    history: translate(CHAT_COPY_KEYS.history),
    inspectSource: translate(CHAT_COPY_KEYS.inspectSource),
    loading: translate(CHAT_COPY_KEYS.loading),
    locationUnavailable: translate(CHAT_COPY_KEYS.locationUnavailable),
    message: translate(CHAT_COPY_KEYS.message),
    newChat: translate(CHAT_COPY_KEYS.newChat),
    newSession: translate(CHAT_COPY_KEYS.newSession),
    noSessions: translate(CHAT_COPY_KEYS.noSessions),
    page: translate(CHAT_COPY_KEYS.page),
    regenerate: translate(CHAT_COPY_KEYS.regenerate),
    rename: translate(CHAT_COPY_KEYS.rename),
    responseComplete: translate(CHAT_COPY_KEYS.responseComplete),
    send: translate(CHAT_COPY_KEYS.send),
    sessions: translate(CHAT_COPY_KEYS.sessions),
    snippetUnavailable: translate(CHAT_COPY_KEYS.snippetUnavailable),
    source: translate(CHAT_COPY_KEYS.source),
    sources: translate(CHAT_COPY_KEYS.sources),
    stop: translate(CHAT_COPY_KEYS.stop),
    thanks: translate(CHAT_COPY_KEYS.thanks),
    title: translate(CHAT_COPY_KEYS.title),
    you: translate(CHAT_COPY_KEYS.you),
  } satisfies ChatCopy
}

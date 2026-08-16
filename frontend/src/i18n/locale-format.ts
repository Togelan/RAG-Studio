import type { LocaleTranslations } from "./locale-runtime"

type CountLocaleMessageKey =
  | "chat_session_message_count"
  | "chat_retry_after"
  | "settings_upload_file_types_helper"
  | "ingestion_batch_limit"

type NameLocaleMessageKey =
  | "ingestion_delete_document_aria"
  | "ingestion_delete_document_message"
  | "ingestion_upload_file_progress"

type LocaleMessageKey = CountLocaleMessageKey | NameLocaleMessageKey

type CountInterpolation = {
  readonly count: number
}

type RetryAfterInterpolation = {
  readonly seconds: number
}

type NameInterpolation = {
  readonly name: string
}

export type LocaleMessageFormatter = {
  (key: Exclude<CountLocaleMessageKey, "chat_retry_after">, values: CountInterpolation): string
  (key: "chat_retry_after", values: RetryAfterInterpolation): string
  (key: NameLocaleMessageKey, values: NameInterpolation): string
}

function safeNonnegativeInteger(value: number): string {
  if (!Number.isFinite(value) || value < 0) {
    return "0"
  }

  return String(Math.floor(value))
}

function assertNever(value: never): never {
  throw new TypeError(`Unsupported locale message key: ${value}`)
}

export function formatLocaleMessage(
  translations: LocaleTranslations,
  key: Exclude<CountLocaleMessageKey, "chat_retry_after">,
  values: CountInterpolation,
): string
export function formatLocaleMessage(
  translations: LocaleTranslations,
  key: "chat_retry_after",
  values: RetryAfterInterpolation,
): string
export function formatLocaleMessage(
  translations: LocaleTranslations,
  key: NameLocaleMessageKey,
  values: NameInterpolation,
): string
export function formatLocaleMessage(
  translations: LocaleTranslations,
  key: LocaleMessageKey,
  values: CountInterpolation | NameInterpolation | RetryAfterInterpolation,
): string {
  return formatLocaleMessageTemplate(translations, key, values)
}

function formatLocaleMessageTemplate(
  translations: LocaleTranslations,
  key: LocaleMessageKey,
  values: CountInterpolation | NameInterpolation | RetryAfterInterpolation,
): string {
  const template = translations.get(key)
  if (template === undefined) {
    return key
  }

  switch (key) {
    case "chat_session_message_count":
    case "settings_upload_file_types_helper":
    case "ingestion_batch_limit":
      if ("count" in values) {
        return template.replace("{count}", safeNonnegativeInteger(values.count))
      }
      return key
    case "chat_retry_after":
      if ("seconds" in values) {
        return template.replace("{seconds}", safeNonnegativeInteger(values.seconds))
      }
      return key
    case "ingestion_delete_document_aria":
    case "ingestion_delete_document_message":
    case "ingestion_upload_file_progress":
      if ("name" in values) {
        return template.replace("{name}", values.name)
      }
      return key
    default:
      return assertNever(key)
  }
}

export function createLocaleMessageFormatter(
  translations: LocaleTranslations,
): LocaleMessageFormatter {
  return (
    key: LocaleMessageKey,
    values: CountInterpolation | NameInterpolation | RetryAfterInterpolation,
  ): string => formatLocaleMessageTemplate(translations, key, values)
}

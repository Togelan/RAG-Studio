import ky from "ky"
import { useSyncExternalStore } from "react"
import { z } from "zod"

import { type Locale, localeKeys, type TranslationKey } from "./locale-inventory"
import { readStoredLocale } from "./locale-storage"

export {
  createLocaleMessageFormatter,
  formatLocaleMessage,
  type LocaleMessageFormatter,
} from "./locale-format"

export const LOCALE_ENDPOINT = "/api/ui/locale"
export { LOCALE_STORAGE_KEY, persistBrowserLocale } from "./locale-storage"

export type LocaleSource = "query" | "cookie" | "storage" | "browser" | "default"

export type InitialLocaleInput = {
  readonly search: string
  readonly cookie: string
  readonly storedLocale: string | null
  readonly browserLanguages: readonly string[]
}

export type InitialLocale = {
  readonly locale: Locale
  readonly source: LocaleSource
}

export type LocaleTranslations = ReadonlyMap<TranslationKey, string>

export type LocaleState = {
  readonly locale: Locale
  readonly translations: LocaleTranslations
}

export type LocaleGateway = {
  readonly setLocale: (locale: Locale) => Promise<unknown>
}

export type LocaleHttpResponse = { readonly json: () => Promise<unknown> }

export type LocaleHttpClient = {
  readonly post: (
    url: string,
    options: {
      readonly json: { readonly locale: Locale }
      readonly credentials: "same-origin"
      readonly retry: 0
    },
  ) => LocaleHttpResponse
}

export type LocaleRuntimeOptions = {
  readonly initialLocale: Locale
  readonly initialTranslations: LocaleTranslations
  readonly translationsByLocale?: Readonly<Record<Locale, LocaleTranslations>>
  readonly gateway: LocaleGateway
  readonly persistLocale?: (locale: Locale) => void
}

export type LocaleSwitchResult =
  | { readonly kind: "success"; readonly locale: Locale }
  | { readonly kind: "failure"; readonly reason: "invalid-response" | "request-failed" }

export type LocaleRuntime = {
  readonly getState: () => LocaleState
  readonly setLocale: (locale: Locale) => Promise<LocaleSwitchResult>
  readonly subscribe: (listener: () => void) => () => void
  readonly translate: (key: TranslationKey) => string
}

const LocaleResponseSchema = z.object({
  locale: z.string(),
  translations: z.record(z.string(), z.string()),
})

const requiredInterpolationTokens: ReadonlyMap<TranslationKey, string> = new Map([
  ["chat_session_message_count", "{count}"],
  ["chat_retry_after", "{seconds}"],
  ["settings_upload_file_types_helper", "{count}"],
  ["ingestion_batch_limit", "{count}"],
  ["ingestion_delete_document_aria", "{name}"],
  ["ingestion_delete_document_message", "{name}"],
  ["ingestion_upload_file_progress", "{name}"],
])

export function parseLocale(value: string | null | undefined): Locale | null {
  switch (value) {
    case "en":
      return "en"
    case "ru":
      return "ru"
    default:
      return null
  }
}

function parseLocaleCandidate(value: string | null | undefined): Locale | null {
  return parseLocale(value?.toLowerCase())
}

function queryLocale(search: string): Locale | null {
  return parseLocaleCandidate(new URLSearchParams(search).get("lang"))
}

function cookieLocale(cookie: string): Locale | null {
  for (const value of cookie.split(";")) {
    const [name, rawLocale] = value.trim().split("=", 2)

    if (name === "locale") {
      return parseLocaleCandidate(rawLocale)
    }
  }

  return null
}

function browserLocale(browserLanguages: readonly string[]): Locale | null {
  for (const browserLanguage of browserLanguages) {
    const [language] = browserLanguage.toLowerCase().split("-", 1)
    const locale = parseLocale(language)

    if (locale !== null) return locale
  }

  return null
}

export function resolveInitialLocale(input: InitialLocaleInput): InitialLocale {
  const query = queryLocale(input.search)
  if (query !== null) {
    return { locale: query, source: "query" }
  }

  const cookie = cookieLocale(input.cookie)
  if (cookie !== null) {
    return { locale: cookie, source: "cookie" }
  }

  const storage = parseLocaleCandidate(input.storedLocale)
  if (storage !== null) {
    return { locale: storage, source: "storage" }
  }

  const browser = browserLocale(input.browserLanguages)
  if (browser !== null) {
    return { locale: browser, source: "browser" }
  }

  return { locale: "en", source: "default" }
}

export function createLocaleTranslations(value: unknown): LocaleTranslations | null {
  const parsed = z.record(z.string(), z.string()).safeParse(value)
  if (!parsed.success) {
    return null
  }

  if (Object.keys(parsed.data).length !== localeKeys.length) {
    return null
  }

  const translations = new Map<TranslationKey, string>()
  for (const key of localeKeys) {
    const translation = parsed.data[key]
    const requiredInterpolationToken = requiredInterpolationTokens.get(key)
    if (
      translation === undefined ||
      !translation.trim() ||
      (requiredInterpolationToken !== undefined &&
        !translation.includes(requiredInterpolationToken))
    ) {
      return null
    }
    translations.set(key, translation)
  }

  return translations
}

function parseLocaleResponse(
  value: unknown,
): { readonly locale: Locale; readonly translations: LocaleTranslations } | null {
  const parsed = LocaleResponseSchema.safeParse(value)
  if (!parsed.success) {
    return null
  }

  const locale = parseLocale(parsed.data.locale)
  const translations = createLocaleTranslations(parsed.data.translations)
  if (locale === null || translations === null) {
    return null
  }

  return { locale, translations }
}

export function createLocaleApiClient(http: LocaleHttpClient = ky): LocaleGateway {
  return {
    async setLocale(locale: Locale): Promise<unknown> {
      return http
        .post(LOCALE_ENDPOINT, {
          json: { locale },
          credentials: "same-origin",
          retry: 0,
        })
        .json()
    },
  }
}

export function createLocaleRuntime(options: LocaleRuntimeOptions): LocaleRuntime {
  let state: LocaleState = {
    locale: options.initialLocale,
    translations: options.initialTranslations,
  }
  const listeners = new Set<() => void>()
  let latestLocaleSwitch = 0

  const notify = (): void => {
    for (const listener of listeners) {
      listener()
    }
  }

  return {
    getState: (): LocaleState => state,
    subscribe: (listener: () => void): (() => void) => {
      listeners.add(listener)
      return (): void => {
        listeners.delete(listener)
      }
    },
    translate: (key: TranslationKey): string => state.translations.get(key) ?? key,
    async setLocale(locale: Locale): Promise<LocaleSwitchResult> {
      const switchId = ++latestLocaleSwitch
      const isCurrentSwitch = (): boolean => switchId === latestLocaleSwitch
      const previousState = state
      const bundledTranslations = options.translationsByLocale?.[locale]
      const switchedOptimistically = bundledTranslations !== undefined && state.locale !== locale

      if (switchedOptimistically) {
        state = { locale, translations: bundledTranslations }
        notify()
      }

      try {
        const response = parseLocaleResponse(await options.gateway.setLocale(locale))
        if (!isCurrentSwitch()) {
          return { kind: "success", locale }
        }
        if (response === null || response.locale !== locale) {
          if (switchedOptimistically) {
            state = previousState
            notify()
          }
          return { kind: "failure", reason: "invalid-response" }
        }

        state = response
        options.persistLocale?.(locale)
        notify()
        return { kind: "success", locale }
      } catch (error) {
        if (!isCurrentSwitch()) {
          return { kind: "success", locale }
        }
        if (switchedOptimistically) {
          state = previousState
          notify()
        }
        if (error instanceof Error) {
          return { kind: "failure", reason: "request-failed" }
        }
        throw error
      }
    },
  }
}

export function useLocale(runtime: LocaleRuntime): LocaleState {
  return useSyncExternalStore(runtime.subscribe, runtime.getState, runtime.getState)
}

export function resolveBrowserLocale(): InitialLocale {
  const storedLocale = readStoredLocale()
  return resolveInitialLocale({
    search: window.location.search,
    cookie: document.cookie,
    storedLocale,
    browserLanguages: navigator.languages,
  })
}

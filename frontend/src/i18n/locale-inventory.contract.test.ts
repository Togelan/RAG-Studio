import { act, renderHook } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { localeKeys } from "./locale-inventory"
import {
  createLocaleApiClient,
  createLocaleRuntime,
  createLocaleTranslations,
  formatLocaleMessage,
  LOCALE_ENDPOINT,
  LOCALE_STORAGE_KEY,
  resolveInitialLocale,
  useLocale,
} from "./locale-runtime"

function createResponseTranslations(prefix: string): Record<string, string> {
  const translations: Record<string, string> = {}

  for (const key of localeKeys) translations[key] = `${prefix}:${key}`
  return {
    ...translations,
    chat_session_message_count: `${prefix}: {count}`,
    chat_retry_after: `${prefix}: {seconds}`,
    settings_upload_file_types_helper: `${prefix}: {count}`,
    ingestion_batch_limit: `${prefix}: {count}`,
    ingestion_delete_document_aria: `${prefix}: {name}`,
    ingestion_delete_document_message: `${prefix}: {name}`,
    ingestion_upload_file_progress: `${prefix}: {name}`,
  }
}

describe("React locale contract", () => {
  it("exposes the authoritative default chat session title key", () => {
    expect(localeKeys).toContain("chat_new_session")
  })

  it("resolves query then cookie then local storage then browser/default locale", () => {
    expect(LOCALE_ENDPOINT).toBe("/api/ui/locale")

    const locale = resolveInitialLocale({
      search: "?lang=en",
      cookie: "locale=ru",
      storedLocale: "ru",
      browserLanguages: ["ru-RU"],
    })

    expect(locale).toEqual({ locale: "en", source: "query" })
    expect(
      resolveInitialLocale({
        search: "?lang=fr",
        cookie: "locale=ru",
        storedLocale: "en",
        browserLanguages: ["en-US"],
      }),
    ).toEqual({ locale: "ru", source: "cookie" })
    expect(
      resolveInitialLocale({
        search: "",
        cookie: "",
        storedLocale: "ru",
        browserLanguages: ["en-US"],
      }),
    ).toEqual({ locale: "ru", source: "storage" })
    expect(
      resolveInitialLocale({
        search: "",
        cookie: "",
        storedLocale: null,
        browserLanguages: ["fr-FR"],
      }),
    ).toEqual({ locale: "en", source: "default" })
  })

  it("posts locale changes through the same-origin endpoint boundary", async () => {
    const requests: {
      url: string
      options: {
        json: { locale: string }
        credentials: string
        retry: number
      }
    }[] = []
    const client = createLocaleApiClient({
      post: (url, options) => {
        requests.push({ url, options })
        return {
          json: async () => ({
            locale: options.json.locale,
            translations: createResponseTranslations(options.json.locale),
          }),
        }
      },
    })

    await expect(client.setLocale("ru")).resolves.toEqual({
      locale: "ru",
      translations: createResponseTranslations("ru"),
    })
    expect(requests).toEqual([
      {
        url: "/api/ui/locale",
        options: {
          json: { locale: "ru" },
          credentials: "same-origin",
          retry: 0,
        },
      },
    ])
  })

  it("formats the authoritative session count and Retry-After templates safely", () => {
    const english = createLocaleTranslations({
      ...createResponseTranslations("english"),
      chat_session_message_count: "Messages: {count}",
      chat_retry_after: "Please retry in {seconds} seconds.",
      settings_upload_file_types_helper:
        "TXT, MD, PDF, DOCX or CSV · 50 MB each · {count} files per batch",
    })
    const russian = createLocaleTranslations({
      ...createResponseTranslations("русский"),
      chat_session_message_count: "Сообщений: {count}",
      chat_retry_after: "Повторите попытку через {seconds} с.",
    })

    if (english === null || russian === null) {
      throw new Error("test fixture must contain every locale key")
    }

    expect(formatLocaleMessage(english, "chat_session_message_count", { count: 2 })).toBe(
      "Messages: 2",
    )
    expect(formatLocaleMessage(russian, "chat_retry_after", { seconds: 3 })).toBe(
      "Повторите попытку через 3 с.",
    )
    expect(formatLocaleMessage(english, "chat_retry_after", { seconds: Number.NaN })).toBe(
      "Please retry in 0 seconds.",
    )
    expect(formatLocaleMessage(english, "settings_upload_file_types_helper", { count: 20 })).toBe(
      "TXT, MD, PDF, DOCX or CSV · 50 MB each · 20 files per batch",
    )
  })

  it("rejects a complete map missing a required formatted placeholder", () => {
    expect(
      createLocaleTranslations({
        ...createResponseTranslations("english"),
        chat_session_message_count: "Messages",
      }),
    ).toBeNull()
    expect(
      createLocaleTranslations({
        ...createResponseTranslations("english"),
        chat_retry_after: "Please retry soon.",
      }),
    ).toBeNull()
    expect(
      createLocaleTranslations({
        ...createResponseTranslations("english"),
        settings_upload_file_types_helper:
          "TXT, MD, PDF, DOCX or CSV · 50 MB each · files per batch",
      }),
    ).toBeNull()
  })

  it("updates subscribers and React consumers after the locale endpoint succeeds", async () => {
    const english = createLocaleTranslations(createResponseTranslations("english"))
    if (english === null) {
      throw new Error("test fixture must contain every locale key")
    }

    const runtime = createLocaleRuntime({
      initialLocale: "en",
      initialTranslations: english,
      gateway: {
        setLocale: async (locale) => ({
          locale,
          translations: createResponseTranslations("русский 日本語"),
        }),
      },
    })
    const { result } = renderHook(() => useLocale(runtime))

    await act(async () => {
      const outcome = await runtime.setLocale("ru")
      expect(outcome).toEqual({ kind: "success", locale: "ru" })
    })

    expect(result.current.locale).toBe("ru")
    expect(runtime.translate("welcome_title")).toBe("русский 日本語:welcome_title")
  })

  it("switches to bundled translations before locale persistence resolves", async () => {
    const english = createLocaleTranslations(createResponseTranslations("english"))
    const russian = createLocaleTranslations(createResponseTranslations("russian"))
    if (english === null || russian === null) {
      throw new Error("test fixture must contain every locale key")
    }

    let resolveResponse: ((value: unknown) => void) | undefined
    const persistence = new Promise<unknown>((resolve) => {
      resolveResponse = resolve
    })
    const runtime = createLocaleRuntime({
      initialLocale: "en",
      initialTranslations: english,
      translationsByLocale: { en: english, ru: russian },
      gateway: { setLocale: async () => persistence },
    })
    const subscriberLocales: string[] = []
    const unsubscribe = runtime.subscribe(() => subscriberLocales.push(runtime.getState().locale))

    const pendingSwitch = runtime.setLocale("ru")

    expect(runtime.getState().locale).toBe("ru")
    expect(runtime.translate("welcome_title")).toBe("russian:welcome_title")
    expect(subscriberLocales).toEqual(["ru"])

    resolveResponse?.({ locale: "ru", translations: createResponseTranslations("russian") })
    await expect(pendingSwitch).resolves.toEqual({ kind: "success", locale: "ru" })
    unsubscribe()
  })

  it("rolls back an optimistic bundled switch when locale persistence fails", async () => {
    const english = createLocaleTranslations(createResponseTranslations("english"))
    const russian = createLocaleTranslations(createResponseTranslations("russian"))
    if (english === null || russian === null) {
      throw new Error("test fixture must contain every locale key")
    }

    const persistedLocales: string[] = []
    const runtime = createLocaleRuntime({
      initialLocale: "en",
      initialTranslations: english,
      translationsByLocale: { en: english, ru: russian },
      gateway: { setLocale: async () => Promise.reject(new Error("offline")) },
      persistLocale: (locale) => persistedLocales.push(locale),
    })

    const pendingSwitch = runtime.setLocale("ru")
    expect(runtime.getState().locale).toBe("ru")

    await expect(pendingSwitch).resolves.toEqual({ kind: "failure", reason: "request-failed" })
    expect(runtime.getState().locale).toBe("en")
    expect(runtime.translate("welcome_title")).toBe("english:welcome_title")
    expect(persistedLocales).toEqual([])
  })

  it("persists accepted endpoint switches and retains the last locale when a later request fails", async () => {
    window.localStorage.clear()
    const english = createLocaleTranslations(createResponseTranslations("english"))
    expect(english).not.toBeNull()

    if (english === null) {
      throw new Error("test fixture must contain every locale key")
    }

    const requestedLocales: string[] = []
    const subscriberLocales: string[] = []
    let rejectNextRequest = false
    const runtime = createLocaleRuntime({
      initialLocale: "en",
      initialTranslations: english,
      gateway: {
        setLocale: async (locale) => {
          requestedLocales.push(locale)
          if (rejectNextRequest) {
            return Promise.reject(new Error("offline"))
          }
          return { locale, translations: createResponseTranslations(locale) }
        },
      },
      persistLocale: (locale) => window.localStorage.setItem(LOCALE_STORAGE_KEY, locale),
    })
    const unsubscribe = runtime.subscribe(() => subscriberLocales.push(runtime.getState().locale))
    const { result } = renderHook(() => useLocale(runtime))
    const locationBeforeSwitches = window.location.href

    await act(async () => {
      expect(await runtime.setLocale("ru")).toEqual({ kind: "success", locale: "ru" })
    })
    await act(async () => {
      expect(await runtime.setLocale("en")).toEqual({ kind: "success", locale: "en" })
    })

    rejectNextRequest = true
    await expect(runtime.setLocale("ru")).resolves.toEqual({
      kind: "failure",
      reason: "request-failed",
    })

    expect(LOCALE_ENDPOINT).toBe("/api/ui/locale")
    expect(requestedLocales).toEqual(["ru", "en", "ru"])
    expect(subscriberLocales).toEqual(["ru", "en"])
    expect(result.current.locale).toBe("en")
    expect(window.localStorage.getItem(LOCALE_STORAGE_KEY)).toBe("en")
    expect(window.location.href).toBe(locationBeforeSwitches)
    unsubscribe()
  })

  it("keeps the last complete translations when the locale response is invalid or unavailable", async () => {
    const english = createLocaleTranslations(createResponseTranslations("english"))
    expect(english).not.toBeNull()

    if (english === null) {
      throw new Error("test fixture must contain every locale key")
    }

    const invalidResponseRuntime = createLocaleRuntime({
      initialLocale: "en",
      initialTranslations: english,
      gateway: {
        setLocale: async () => ({ locale: "fr", translations: {} }),
      },
    })
    const unavailableRuntime = createLocaleRuntime({
      initialLocale: "en",
      initialTranslations: english,
      gateway: {
        setLocale: async () => Promise.reject(new Error("offline")),
      },
    })

    await expect(invalidResponseRuntime.setLocale("ru")).resolves.toEqual({
      kind: "failure",
      reason: "invalid-response",
    })
    await expect(unavailableRuntime.setLocale("ru")).resolves.toEqual({
      kind: "failure",
      reason: "request-failed",
    })

    expect(invalidResponseRuntime.getState().locale).toBe("en")
    expect(unavailableRuntime.getState().locale).toBe("en")
    expect(invalidResponseRuntime.translate("welcome_title")).toBe("english:welcome_title")
    expect(unavailableRuntime.translate("welcome_title")).toBe("english:welcome_title")
  })
})

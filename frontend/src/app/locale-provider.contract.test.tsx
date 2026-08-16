import { act, cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it } from "vitest"

import { localeKeys } from "../i18n/locale-inventory"
import { createLocaleRuntime, createLocaleTranslations } from "../i18n/locale-runtime"
import { LocaleProvider, useLocaleContext } from "./locale-provider"

function translations(locale: "en" | "ru") {
  const parsed = createLocaleTranslations({
    ...Object.fromEntries(localeKeys.map((key) => [key, `${locale} ${key}`])),
    chat_session_message_count: locale === "en" ? "Messages: {count}" : "Сообщений: {count}",
    chat_retry_after:
      locale === "en"
        ? "Please retry in {seconds} seconds."
        : "Повторите попытку через {seconds} с.",
    settings_upload_file_types_helper:
      locale === "en"
        ? "TXT, MD, PDF, DOCX or CSV · 50 MB each · {count} files per batch"
        : "TXT, MD, PDF, DOCX или CSV · до 50 МБ каждый · {count} файлов в пакете",
    ingestion_batch_limit: locale === "en" ? "Files: {count}" : "Файлов: {count}",
    ingestion_delete_document_aria: locale === "en" ? "Delete {name}" : "Удалить {name}",
    ingestion_delete_document_message: locale === "en" ? "Delete {name}" : "Удалить {name}",
    ingestion_upload_file_progress: locale === "en" ? "{name} progress" : "Загрузка {name}",
    locale_update_unavailable:
      locale === "en" ? "Locale update unavailable" : "Не удалось обновить язык",
  })
  if (parsed === null) {
    throw new Error("test translations must be complete")
  }
  return parsed
}

function LocaleMessage(): React.JSX.Element {
  const { format, setLocale, t } = useLocaleContext()

  return (
    <>
      <h1>{t("welcome_title")}</h1>
      <output>{format("chat_session_message_count", { count: 2 })}</output>
      <button onClick={() => void setLocale("ru")} type="button">
        Russian
      </button>
    </>
  )
}

afterEach(cleanup)

describe("LocaleProvider formatter", () => {
  it("rerenders an authoritative interpolated message after a locale change", async () => {
    const user = userEvent.setup()
    const runtime = createLocaleRuntime({
      gateway: {
        setLocale: async (locale) => ({
          locale,
          translations: Object.fromEntries(translations(locale)),
        }),
      },
      initialLocale: "en",
      initialTranslations: translations("en"),
    })

    render(
      <LocaleProvider runtime={runtime}>
        <LocaleMessage />
      </LocaleProvider>,
    )

    expect(screen.getByText("Messages: 2")).toBeVisible()

    await user.click(screen.getByRole("button", { name: "Russian" }))

    expect(await screen.findByText("Сообщений: 2")).toBeVisible()
  })

  it("updates the document language before the locale POST settles", async () => {
    const user = userEvent.setup()
    const english = translations("en")
    const russian = translations("ru")
    let resolveRussian: ((value: unknown) => void) | undefined
    const russianResponse = new Promise<unknown>((resolve) => {
      resolveRussian = resolve
    })
    const runtime = createLocaleRuntime({
      gateway: {
        setLocale: async (locale) =>
          locale === "ru"
            ? russianResponse
            : { locale, translations: Object.fromEntries(translations(locale)) },
      },
      initialLocale: "en",
      initialTranslations: english,
      translationsByLocale: { en: english, ru: russian },
    })
    document.documentElement.lang = "en"

    render(
      <LocaleProvider runtime={runtime}>
        <LocaleMessage />
      </LocaleProvider>,
    )

    await user.click(screen.getByRole("button", { name: "Russian" }))

    await waitFor(() => expect(document.documentElement.lang).toBe("ru"))
    expect(screen.getByText(/: 2$/)).toBeVisible()

    await act(async () => {
      resolveRussian?.({ locale: "ru", translations: Object.fromEntries(russian) })
    })
  })

  it("does not race a pending RU switch with a mount request or split the heading", async () => {
    const user = userEvent.setup()
    const english = translations("en")
    const russian = translations("ru")
    const requests: string[] = []
    let resolveRussian: ((value: unknown) => void) | undefined
    const russianResponse = new Promise<unknown>((resolve) => {
      resolveRussian = resolve
    })
    const runtime = createLocaleRuntime({
      gateway: {
        setLocale: async (locale) => {
          requests.push(locale)
          return locale === "ru"
            ? russianResponse
            : { locale, translations: Object.fromEntries(english) }
        },
      },
      initialLocale: "en",
      initialTranslations: english,
      translationsByLocale: { en: english, ru: russian },
    })
    document.documentElement.lang = "en"

    render(
      <LocaleProvider runtime={runtime}>
        <LocaleMessage />
      </LocaleProvider>,
    )
    expect(requests).toEqual([])

    await user.click(screen.getByRole("button", { name: "Russian" }))
    await waitFor(() => expect(document.documentElement.lang).toBe("ru"))
    expect(screen.getByRole("heading")).toHaveTextContent("ru welcome_title")
    expect(requests).toEqual(["ru"])

    await act(async () => {
      resolveRussian?.({ locale: "ru", translations: Object.fromEntries(russian) })
    })
    expect(runtime.getState().locale).toBe("ru")
  })

  it("renders locale-update failure status from the authoritative Russian map", async () => {
    const user = userEvent.setup()
    const runtime = createLocaleRuntime({
      gateway: {
        setLocale: async () => Promise.reject(new Error("offline")),
      },
      initialLocale: "ru",
      initialTranslations: translations("ru"),
    })

    render(
      <LocaleProvider runtime={runtime}>
        <LocaleMessage />
      </LocaleProvider>,
    )

    await user.click(screen.getByRole("button", { name: "Russian" }))

    await waitFor(() =>
      expect(screen.getAllByRole("status").at(-1)).toHaveTextContent("Не удалось обновить язык"),
    )
  })
})

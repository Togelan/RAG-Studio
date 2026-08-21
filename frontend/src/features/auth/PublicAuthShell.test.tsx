import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"

import { LocaleProvider } from "../../app/locale-provider"
import { localeKeys } from "../../i18n/locale-inventory"
import { createLocaleRuntime, createLocaleTranslations } from "../../i18n/locale-runtime"
import { PublicAuthShell } from "./PublicAuthShell"

function localeValues(locale: "en" | "ru"): Record<string, string> {
  return {
    ...Object.fromEntries(localeKeys.map((key) => [key, `${locale} ${key}`])),
    chat_session_message_count: `${locale} {count}`,
    chat_retry_after: `${locale} {seconds}`,
    settings_upload_file_types_helper: `${locale} {count}`,
    ingestion_batch_limit: `${locale} {count}`,
    ingestion_delete_document_aria: `${locale} {name}`,
    ingestion_delete_document_message: `${locale} {name}`,
    ingestion_upload_file_progress: `${locale} {name}`,
  }
}

function renderShell(): ReturnType<typeof createLocaleRuntime> {
  const translations = createLocaleTranslations(localeValues("en"))
  if (translations === null) throw new Error("test locale values must be complete")
  const runtime = createLocaleRuntime({
    gateway: {
      setLocale: async (locale) => ({ locale, translations: localeValues(locale) }),
    },
    initialLocale: "en",
    initialTranslations: translations,
  })
  render(
    <LocaleProvider runtime={runtime}>
      <MemoryRouter>
        <PublicAuthShell>
          <p>Public form</p>
        </PublicAuthShell>
      </MemoryRouter>
    </LocaleProvider>,
  )
  return runtime
}

describe("PublicAuthShell", () => {
  it("uses the dark product menu to switch locale without a native select", async () => {
    const user = userEvent.setup()
    const runtime = renderShell()

    expect(screen.queryByRole("combobox")).not.toBeInTheDocument()
    await user.click(screen.getByLabelText("en aria_lang_selector"))
    const localePanel = document.querySelector<HTMLDivElement>(".rs-locale-menu__panel")
    if (localePanel === null) throw new Error("locale panel must render")
    expect(within(localePanel).getByRole("button", { name: "en aria_english" })).toHaveAttribute(
      "aria-pressed",
      "true",
    )
    await user.click(within(localePanel).getByRole("button", { name: "en aria_russian" }))

    await waitFor(() => expect(runtime.getState().locale).toBe("ru"))
    expect(document.documentElement).toHaveAttribute("lang", "ru")
  })

  it("opens from the keyboard and restores focus when Escape closes it", async () => {
    const user = userEvent.setup()
    renderShell()

    const trigger = screen.getByLabelText("en aria_lang_selector")
    trigger.focus()
    await user.keyboard("{Enter}")
    expect(trigger).toHaveAttribute("aria-expanded", "true")
    await user.keyboard("{Escape}")

    expect(trigger).toHaveAttribute("aria-expanded", "false")
    expect(trigger).toHaveFocus()
  })
})

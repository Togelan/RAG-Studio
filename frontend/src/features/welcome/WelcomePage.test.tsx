import { cleanup, render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { afterEach, describe, expect, it } from "vitest"

import { LocaleProvider } from "../../app/locale-provider"
import { localeKeys } from "../../i18n/locale-inventory"
import {
  createLocaleRuntime,
  createLocaleTranslations,
  type LocaleTranslations,
} from "../../i18n/locale-runtime"
import { WelcomePage } from "./WelcomePage"

function createWelcomeTranslations(): LocaleTranslations {
  const translations = createLocaleTranslations(
    Object.fromEntries(
      localeKeys.map((key) => {
        switch (key) {
          case "welcome_title":
            return [key, "Welcome to RAG Studio"]
          case "welcome_subtitle":
            return [key, "Your private, local document chat assistant."]
          case "welcome.get_started":
            return [key, "Get Started"]
          case "welcome.video_placeholder":
            return [key, "Video tutorial coming soon"]
          case "chat_session_message_count":
            return [key, "Messages: {count}"]
          case "chat_retry_after":
            return [key, "Please retry in {seconds} seconds."]
          case "settings_upload_file_types_helper":
            return [key, "TXT, MD, PDF, DOCX or CSV · 50 MB each · {count} files per batch"]
          case "ingestion_batch_limit":
            return [key, "Choose at most {count} files per batch."]
          case "ingestion_delete_document_aria":
          case "ingestion_delete_document_message":
            return [key, "Delete {name}"]
          case "ingestion_upload_file_progress":
            return [key, "{name} progress"]
          default:
            return [key, key]
        }
      }),
    ),
  )

  if (translations === null) {
    throw new Error("Welcome test translations must be complete")
  }

  return translations
}

function renderWelcome(route: string): void {
  const runtime = createLocaleRuntime({
    gateway: { setLocale: async () => ({}) },
    initialLocale: "en",
    initialTranslations: createWelcomeTranslations(),
  })

  render(
    <LocaleProvider runtime={runtime}>
      <MemoryRouter initialEntries={[route]}>
        <WelcomePage />
      </MemoryRouter>
    </LocaleProvider>,
  )
}

afterEach(cleanup)

describe("React Welcome journey", () => {
  it.each([
    ["/", "/settings"],
    ["/app", "/app/settings"],
  ])("keeps Get Started alias-aware from %s", (route, expectedHref) => {
    renderWelcome(route)

    expect(screen.getByRole("link", { name: "Get Started" })).toHaveAttribute("href", expectedHref)
  })

  it("renders localized purpose copy and an honest tutorial placeholder", () => {
    renderWelcome("/")

    expect(screen.getByText("Your private, local document chat assistant.")).toBeVisible()
    expect(screen.getByText("Video tutorial coming soon")).toBeVisible()
    expect(screen.getByLabelText("Video tutorial coming soon")).toHaveAttribute(
      "aria-disabled",
      "true",
    )
  })

  it("does not render legacy counters, fake metrics, or unsupported controls", () => {
    renderWelcome("/")

    expect(screen.queryByText(/10Г—|100\+|hours\/month/i)).not.toBeInTheDocument()
    expect(screen.queryByRole("button")).not.toBeInTheDocument()
    expect(screen.queryByText(/dashboard|analytics|billing/i)).not.toBeInTheDocument()
  })
})

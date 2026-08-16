import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { afterEach, describe, expect, it } from "vitest"

import { RagStudioApp } from "../../App"
import { LocaleProvider } from "../../app/locale-provider"
import type { HealthGateway } from "../../features/health/health-status"
import { localeKeys } from "../../i18n/locale-inventory"
import {
  createLocaleRuntime,
  createLocaleTranslations,
  type LocaleRuntime,
} from "../../i18n/locale-runtime"

function translations(prefix: string): ReadonlyMap<(typeof localeKeys)[number], string> {
  const parsed = createLocaleTranslations(localeFixtureValues(prefix))
  if (parsed === null) {
    throw new Error("test translations must be complete")
  }
  return parsed
}

function localeFixtureValues(prefix: string): Record<string, string> {
  return {
    ...Object.fromEntries(localeKeys.map((key) => [key, `${prefix} ${key}`])),
    chat_session_message_count: `${prefix} {count}`,
    chat_retry_after: `${prefix} {seconds}`,
    settings_upload_file_types_helper: `${prefix} {count}`,
    ingestion_batch_limit: `${prefix} {count}`,
    ingestion_delete_document_aria: `${prefix} {name}`,
    ingestion_delete_document_message: `${prefix} {name}`,
    ingestion_upload_file_progress: `${prefix} {name}`,
  }
}

function createRuntime(
  initialLocale: "en" | "ru" = "en",
  translationPrefix: string = initialLocale,
): LocaleRuntime {
  return createLocaleRuntime({
    gateway: {
      setLocale: async (locale) => ({
        locale,
        translations: localeFixtureValues(locale),
      }),
    },
    initialLocale,
    initialTranslations: translations(translationPrefix),
  })
}

const readyHealthGateway: HealthGateway = {
  getStatus: async () => ({ api_key_configured: true, status: "ready" }),
}

function renderShell(
  initialEntry: string,
  healthGateway: HealthGateway = readyHealthGateway,
): LocaleRuntime {
  const runtime = createRuntime()
  render(
    <LocaleProvider runtime={runtime}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <RagStudioApp healthGateway={healthGateway} />
      </MemoryRouter>
    </LocaleProvider>,
  )
  return runtime
}

afterEach(cleanup)

describe("Stage 2 AppShell", () => {
  it("keeps React aliases active and generates alias-aware internal links", async () => {
    renderShell("/app/settings")

    expect(await screen.findByRole("heading", { name: "en settings_title" })).toBeVisible()
    expect(screen.getAllByRole("link", { name: "en nav_settings" })[0]).toHaveAttribute(
      "aria-current",
      "page",
    )
    expect(screen.getAllByRole("link", { name: "en nav_welcome" })[0]).toHaveAttribute(
      "href",
      "/app",
    )
    expect(screen.getAllByRole("link", { name: "en nav_chat" })[0]).toHaveAttribute(
      "href",
      "/app/chat",
    )
    expect(screen.queryByRole("link", { name: /Dashboard/iu })).not.toBeInTheDocument()
    const disabledDashboard = screen
      .getAllByText("en nav_dashboard")
      .map((element) => element.closest('[aria-disabled="true"]'))
      .find((element) => element !== null)
    if (disabledDashboard === undefined || disabledDashboard === null) {
      throw new Error("Dashboard must remain visibly disabled")
    }
    expect(disabledDashboard).toBeVisible()
    expect(screen.getAllByText("en nav_coming_soon")[0]).toBeVisible()
  })

  it("assigns the wide workspace layout only to Chat routes", async () => {
    renderShell("/chat")

    expect(await screen.findByRole("heading", { name: "en chat_title" })).toBeVisible()
    expect(document.querySelector(".rs-shell")).toHaveClass("rs-shell--workspace")

    cleanup()
    renderShell("/settings")

    expect(await screen.findByRole("heading", { name: "en settings_title" })).toBeVisible()
    expect(document.querySelector(".rs-shell")).not.toHaveClass("rs-shell--workspace")
  })

  it("switches the shell locale without a page reload and persists the active translation state", async () => {
    const user = userEvent.setup()
    const runtime = renderShell("/")

    await user.selectOptions(screen.getByRole("combobox", { name: "en aria_lang_selector" }), "ru")

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "ru welcome_title" })).toBeVisible(),
    )
    expect(runtime.getState().locale).toBe("ru")
    expect(document.documentElement).toHaveAttribute("lang", "ru")
    const disabledDashboard = screen
      .getAllByText("ru nav_dashboard")
      .map((element) => element.closest('[aria-disabled="true"]'))
      .find((element) => element !== null)
    if (disabledDashboard === undefined || disabledDashboard === null) {
      throw new Error("Russian Dashboard must remain visibly disabled")
    }
    expect(disabledDashboard).toBeVisible()
    expect(screen.getAllByText("ru nav_coming_soon")[0]).toBeVisible()
  })

  it("renders the authoritative initial Russian locale without a mount request", async () => {
    const runtime = createRuntime("ru")
    render(
      <LocaleProvider runtime={runtime}>
        <MemoryRouter initialEntries={["/"]}>
          <RagStudioApp healthGateway={readyHealthGateway} />
        </MemoryRouter>
      </LocaleProvider>,
    )

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "ru welcome_title" })).toBeVisible(),
    )
    expect(document.documentElement).toHaveAttribute("lang", "ru")
  })

  it("opens the compact navigation with the keyboard and returns focus after Escape", async () => {
    const user = userEvent.setup()
    renderShell("/")

    const trigger = await screen.findByRole("button", { name: "en aria_toggle_menu" })
    await user.click(trigger)
    expect(screen.getByRole("dialog", { name: "en aria_mobile_nav" })).toBeVisible()
    await user.keyboard("{Escape}")
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })
})

import { act, cleanup, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { LocaleProvider } from "../../app/locale-provider"
import { localeKeys } from "../../i18n/locale-inventory"
import { createLocaleRuntime, createLocaleTranslations } from "../../i18n/locale-runtime"
import { type HealthGateway, HealthStatus } from "./health-status"

function runtime() {
  const translations = createLocaleTranslations(localeFixtureValues())
  if (translations === null) {
    throw new Error("test translations must be complete")
  }
  return createLocaleRuntime({
    gateway: {
      setLocale: async () => ({
        locale: "en",
        translations: localeFixtureValues(),
      }),
    },
    initialLocale: "en",
    initialTranslations: translations,
  })
}

function localeFixtureValues(): Record<string, string> {
  return {
    ...Object.fromEntries(localeKeys.map((key) => [key, `label ${key}`])),
    chat_session_message_count: "Messages: {count}",
    chat_retry_after: "Please retry in {seconds} seconds.",
    settings_upload_file_types_helper: "Files: {count}",
    ingestion_batch_limit: "Files: {count}",
    ingestion_delete_document_aria: "Delete {name}",
    ingestion_delete_document_message: "Delete {name}",
    ingestion_upload_file_progress: "{name} progress",
  }
}

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

describe("HealthStatus", () => {
  it("shows textual ready/degraded/offline states and clears the polling timer on unmount", async () => {
    vi.useFakeTimers()
    const getStatus = vi.fn<HealthGateway["getStatus"]>()
    getStatus.mockResolvedValue({ api_key_configured: true, status: "ready" })
    const view = render(
      <LocaleProvider runtime={runtime()}>
        <HealthStatus gateway={{ getStatus }} />
      </LocaleProvider>,
    )

    await act(async () => {
      await Promise.resolve()
    })
    expect(screen.getByRole("status")).toHaveTextContent("label status_ready")
    expect(getStatus).toHaveBeenCalledTimes(1)
    view.unmount()
    await vi.advanceTimersByTimeAsync(30_000)
    expect(getStatus).toHaveBeenCalledTimes(1)
  })

  it("reports an offline failure with a text label instead of a color-only indicator", async () => {
    const gateway: HealthGateway = { getStatus: async () => Promise.reject(new Error("offline")) }
    render(
      <LocaleProvider runtime={runtime()}>
        <HealthStatus gateway={gateway} />
      </LocaleProvider>,
    )

    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent("label status_disconnected"),
    )
  })
})

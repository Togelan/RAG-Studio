import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import ruMessages from "../../../../src/api/locales/ru.json"
import type { TranslationKey } from "../../i18n/locale-inventory"
import { SettingsPage } from "./SettingsPage"
import {
  createIngestionApi,
  createSettingsApi,
  SETTINGS_FIXTURE,
} from "./SettingsPage.test-helpers"
import type { SettingsApi } from "./settings-api"

const localeMock = vi.hoisted(() => ({
  locale: "en" as "en" | "ru",
  messages: {} as Readonly<Record<string, string>>,
}))

vi.mock("../../app/locale-provider", () => ({
  useLocaleContext: () => ({
    locale: localeMock.locale,
    t: (key: TranslationKey) => localeMock.messages[key] ?? key,
    format: (key: TranslationKey, values: { readonly count?: number; readonly name?: string }) =>
      (localeMock.messages[key] ?? key)
        .replace("{count}", String(values.count))
        .replace("{name}", String(values.name)),
  }),
}))

afterEach(() => {
  cleanup()
  localeMock.locale = "en"
  localeMock.messages = {}
})

describe("SettingsPage loading and localization", () => {
  it("ignores a stale load after the Settings gateway changes", async () => {
    let resolveOld: ((value: Awaited<ReturnType<SettingsApi["load"]>>) => void) | undefined
    const oldLoad = new Promise<Awaited<ReturnType<SettingsApi["load"]>>>((resolve) => {
      resolveOld = resolve
    })
    const oldApi = createSettingsApi({ load: vi.fn(() => oldLoad) })
    const newApi = createSettingsApi({
      load: vi.fn(() =>
        Promise.resolve({ ...SETTINGS_FIXTURE, model: "new-model", api_key: null }),
      ),
      models: vi.fn(() =>
        Promise.resolve({ provider: "deepseek" as const, models: ["new-model"], cached: false }),
      ),
    })
    const view = render(<SettingsPage ingestion={createIngestionApi()} settings={oldApi} />)

    view.rerender(<SettingsPage ingestion={createIngestionApi()} settings={newApi} />)
    expect(await screen.findByLabelText("settings_model_label")).toHaveValue("new-model")
    resolveOld?.({ ...SETTINGS_FIXTURE, model: "stale-model", api_key: null })
    await Promise.resolve()

    expect(screen.getByLabelText("settings_model_label")).toHaveValue("new-model")
  })

  it("keeps the current model list when an older refresh completes last", async () => {
    let resolveStale: ((value: Awaited<ReturnType<SettingsApi["models"]>>) => void) | undefined
    const stale = new Promise<Awaited<ReturnType<SettingsApi["models"]>>>((resolve) => {
      resolveStale = resolve
    })
    const models = vi
      .fn<SettingsApi["models"]>()
      .mockResolvedValueOnce({ provider: "deepseek", models: ["deepseek-chat"], cached: true })
      .mockImplementationOnce(() => stale)
      .mockResolvedValueOnce({ provider: "deepseek", models: ["current-model"], cached: false })
    render(
      <SettingsPage ingestion={createIngestionApi()} settings={createSettingsApi({ models })} />,
    )
    await screen.findByLabelText("settings_model_label")
    const refresh = screen.getByRole("button", { name: "settings_refresh_models" })

    await userEvent.click(refresh)
    await userEvent.click(refresh)
    await waitFor(() =>
      expect(screen.getByLabelText("settings_model_label")).toHaveValue("current-model"),
    )
    resolveStale?.({ provider: "deepseek", models: ["stale-model"], cached: false })
    await Promise.resolve()

    expect(screen.getByLabelText("settings_model_label")).toHaveValue("current-model")
  })

  it("does not let the initial model request overwrite a newer manual refresh", async () => {
    let resolveInitial: ((value: Awaited<ReturnType<SettingsApi["models"]>>) => void) | undefined
    const initial = new Promise<Awaited<ReturnType<SettingsApi["models"]>>>((resolve) => {
      resolveInitial = resolve
    })
    const models = vi
      .fn<SettingsApi["models"]>()
      .mockImplementationOnce(() => initial)
      .mockResolvedValueOnce({ provider: "deepseek", models: ["current-model"], cached: false })
    render(
      <SettingsPage ingestion={createIngestionApi()} settings={createSettingsApi({ models })} />,
    )
    const refresh = await screen.findByRole("button", { name: "settings_refresh_models" })

    await userEvent.click(refresh)
    await waitFor(() =>
      expect(screen.getByLabelText("settings_model_label")).toHaveValue("current-model"),
    )
    resolveInitial?.({ provider: "deepseek", models: ["stale-model"], cached: true })
    await Promise.resolve()

    expect(screen.getByLabelText("settings_model_label")).toHaveValue("current-model")
    expect(screen.queryByText("settings_cached_model_list")).not.toBeInTheDocument()
  })

  it("keeps the saved model usable and shows a safe provider fallback", async () => {
    const hostile = "provider SDK /private/path secret"
    render(
      <SettingsPage
        ingestion={createIngestionApi()}
        settings={createSettingsApi({
          models: vi.fn(() => Promise.reject(new Error(hostile))),
        })}
      />,
    )

    expect(await screen.findByLabelText("settings_model_label")).toHaveValue("deepseek-chat")
    expect(screen.getByText("settings_provider_list_unavailable")).toBeVisible()
    expect(screen.queryByText(hostile)).not.toBeInTheDocument()
  })

  it("renders the observed Settings chrome from the authoritative Russian map", async () => {
    localeMock.locale = "ru"
    localeMock.messages = ruMessages
    render(
      <SettingsPage
        ingestion={createIngestionApi()}
        settings={createSettingsApi({
          models: vi.fn(() => Promise.reject(new Error("offline"))),
        })}
      />,
    )
    await screen.findByLabelText(ruMessages.settings_model_label)

    const keys = [
      "settings_workspace_eyebrow",
      "settings_local_encrypted_status",
      "settings_provider_list_unavailable",
      "settings_generation",
      "settings_answer_behavior",
      "settings_index_behavior",
      "settings_observability",
      "settings_model_connection",
      "settings_stored_keys_helper",
      "settings_all_changes_saved",
      "settings_discard_changes",
    ] as const
    for (const key of keys) expect(screen.getByText(ruMessages[key])).toBeVisible()
    expect(screen.queryByText(ruMessages.settings_knowledge_index)).not.toBeInTheDocument()
    expect(
      screen.getAllByRole("option", {
        name: new RegExp(ruMessages.settings_provider_coming_soon, "u"),
      }),
    ).toHaveLength(3)

    for (const english of [
      "Configuration workspace",
      "Local encrypted settings",
      "Provider list unavailable; safe defaults shown.",
      "Generation",
      "Answer behavior",
      "Index behavior",
      "Observability",
      "Model connection",
      "Stored keys stay masked. Enter a value only when replacing the key.",
      "All changes saved",
      "Unsaved changes",
      "Cached model list",
      "Discard changes",
      "Loading settings",
      "Settings are temporarily unavailable. Please try again.",
    ]) {
      expect(screen.queryByText(english)).not.toBeInTheDocument()
    }
    expect(screen.queryByText(/coming soon/u)).not.toBeInTheDocument()
  })
})

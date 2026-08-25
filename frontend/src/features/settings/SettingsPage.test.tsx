import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ApiError } from "../../api/errors"
import type { TranslationKey } from "../../i18n/locale-inventory"
import { SettingsPage } from "./SettingsPage"
import { createIngestionApi, createSettingsApi } from "./SettingsPage.test-helpers"

vi.mock("../../app/locale-provider", () => ({
  useLocaleContext: () => ({
    locale: "en",
    t: (key: TranslationKey) => key,
    format: (key: TranslationKey, values: { readonly count?: number; readonly name?: string }) =>
      `${key}:${values.count ?? values.name}`,
  }),
}))

afterEach(() => cleanup())

interface FileSystemModule {
  readFileSync(path: string, encoding: "utf8"): string
}

describe("SettingsPage save lifecycle", () => {
  it("reserves the fixed mobile navigation below Settings content", async () => {
    render(<SettingsPage ingestion={createIngestionApi()} settings={createSettingsApi()} />)
    const saveForm = (await screen.findByRole("button", { name: "settings_save" })).closest("form")
    expect(saveForm).toHaveClass("rs-settings-savebar")
    const moduleName = ["node", "fs"].join(":")
    const fileSystem = (await import(moduleName)) as unknown as FileSystemModule
    const styles = fileSystem.readFileSync("src/features/settings/settings.css", "utf8")
    expect(styles).toMatch(
      /@media \(max-width: 560px\) \{[\s\S]*?\.rs-settings-page\s*\{\s*padding-bottom:\s*var\(--rs-layout-bottom-nav-reserve\);/u,
    )
  })

  it("does not pin the multi-row save actions over mobile form controls", async () => {
    render(<SettingsPage ingestion={createIngestionApi()} settings={createSettingsApi()} />)
    await screen.findByRole("button", { name: "settings_save" })
    const moduleName = ["node", "fs"].join(":")
    const fileSystem = (await import(moduleName)) as unknown as FileSystemModule
    const styles = fileSystem.readFileSync("src/features/settings/settings.css", "utf8")

    expect(styles).toMatch(
      /@media \(max-width: 560px\) \{[\s\S]*?\.rs-settings-savebar--sticky\s*\{\s*position:\s*static;/u,
    )
  })

  it("keeps dirty save actions in document flow above tablet and desktop form controls", async () => {
    render(<SettingsPage ingestion={createIngestionApi()} settings={createSettingsApi()} />)
    await screen.findByRole("button", { name: "settings_save" })
    const moduleName = ["node", "fs"].join(":")
    const fileSystem = (await import(moduleName)) as unknown as FileSystemModule
    const styles = fileSystem.readFileSync("src/features/settings/settings.css", "utf8")

    expect(styles).toMatch(
      /\.rs-settings-savebar--sticky\s*\{\s*position:\s*static;\s*z-index:\s*auto;\s*bottom:\s*auto;\s*box-shadow:\s*none;/u,
    )
    expect(styles).not.toMatch(/\.rs-settings-savebar--sticky\s*\{\s*position:\s*sticky;/u)
  })

  it("tracks clean, dirty, reverted, discarded, and newly saved baselines", async () => {
    const save = vi.fn((draft) => Promise.resolve({ ...draft, chunks_changed: false }))
    render(<SettingsPage ingestion={createIngestionApi()} settings={createSettingsApi({ save })} />)
    const saveButton = await screen.findByRole("button", { name: "settings_save" })
    const discardButton = screen.getByRole("button", { name: "settings_discard_changes" })
    const topK = screen.getByLabelText("settings_top_k_label")
    const saveForm = saveButton.closest("form")

    expect(saveButton).toBeDisabled()
    expect(discardButton).toBeDisabled()
    expect(saveForm).not.toHaveClass("rs-settings-savebar--sticky")
    expect(screen.getByText("settings_all_changes_saved")).toBeVisible()

    await userEvent.selectOptions(topK, "10")
    expect(saveButton).toBeEnabled()
    expect(discardButton).toBeEnabled()
    expect(saveForm).toHaveClass("rs-settings-savebar--sticky")
    expect(screen.getByText("settings_unsaved_changes")).toBeVisible()

    await userEvent.selectOptions(topK, "5")
    expect(saveButton).toBeDisabled()

    await userEvent.selectOptions(topK, "10")
    await userEvent.click(discardButton)
    expect(topK).toHaveValue("5")
    expect(saveButton).toBeDisabled()

    await userEvent.selectOptions(topK, "10")
    await userEvent.click(saveButton)
    await screen.findByText("settings_saved")
    expect(save).toHaveBeenCalledOnce()
    expect(saveButton).toBeDisabled()
    expect(saveForm).not.toHaveClass("rs-settings-savebar--sticky")
    expect(topK).toHaveValue("10")
  })

  it.each(["click", "keyboard"] as const)(
    "activates a direct Max tokens save through %s user input",
    async (activation) => {
      const save = vi.fn((draft) => Promise.resolve({ ...draft, chunks_changed: false }))
      render(
        <SettingsPage ingestion={createIngestionApi()} settings={createSettingsApi({ save })} />,
      )
      const maxTokens = await screen.findByLabelText("settings_max_tokens_label")
      const saveButton = screen.getByRole("button", { name: "settings_save" })
      expect(saveButton).toHaveAttribute("type", "submit")
      await userEvent.selectOptions(maxTokens, "4096")

      if (activation === "click") {
        await userEvent.click(saveButton)
      } else {
        saveButton.focus()
        await userEvent.keyboard("{Enter}")
      }

      await waitFor(() => expect(save).toHaveBeenCalledOnce())
      expect(save).toHaveBeenCalledWith(
        expect.objectContaining({ max_tokens: 4096 }),
        undefined,
        expect.any(AbortSignal),
      )
      await screen.findByText("settings_saved")
      expect(saveButton).toBeDisabled()
    },
  )

  it("atomically persists a replacement key with settings from the Save button", async () => {
    const validateKey = vi.fn()
    const save = vi.fn((draft) => Promise.resolve({ ...draft, chunks_changed: false }))
    render(
      <SettingsPage
        ingestion={createIngestionApi()}
        settings={createSettingsApi({ save, validateKey })}
      />,
    )
    await userEvent.type(await screen.findByLabelText("settings_api_key_label"), "replacement-key")

    await userEvent.click(screen.getByRole("button", { name: "settings_save" }))

    await waitFor(() => expect(save).toHaveBeenCalledOnce())
    expect(save).toHaveBeenCalledWith(
      expect.objectContaining({ provider: "deepseek" }),
      "replacement-key",
      expect.any(AbortSignal),
    )
    expect(validateKey).not.toHaveBeenCalled()
    expect(screen.getByRole("button", { name: "settings_save" })).toBeDisabled()
  })

  it("keeps prior state when the atomic settings save rejects a replacement key", async () => {
    const save = vi.fn(() => Promise.reject(new ApiError(400, "sanitized", null)))
    const api = createSettingsApi({
      save,
      validateKey: vi.fn(),
    })
    render(<SettingsPage ingestion={createIngestionApi()} settings={api} />)
    await screen.findByLabelText("settings_api_key_label")

    await userEvent.type(screen.getByLabelText("settings_api_key_label"), "replacement-key")
    await userEvent.click(screen.getByRole("button", { name: "settings_save" }))

    expect(await screen.findByRole("alert")).toHaveTextContent("settings_invalid_key")
    expect(save).toHaveBeenCalledOnce()
    expect(screen.getByLabelText("settings_api_key_label")).toHaveValue("replacement-key")
    expect(screen.queryByText("sanitized")).not.toBeInTheDocument()
  })

  it("asks before persistence and Skip performs the settings POST", async () => {
    const ingest = createIngestionApi()
    vi.mocked(ingest.documents).mockResolvedValue({
      documents: [
        {
          doc_id: "doc-a",
          filename: "a.txt",
          chunks_count: 1,
          chunk_size: 512,
          chunk_overlap: 64,
          created_at: "2026-08-15T00:00:00Z",
          strategy: "recursive",
          schema_version: 1,
        },
      ],
      total: 1,
      next_cursor: null,
      truncated: false,
    })
    const save = vi.fn((draft) => Promise.resolve({ ...draft, chunks_changed: true }))
    render(<SettingsPage ingestion={ingest} settings={createSettingsApi({ save })} />)
    await screen.findByRole("button", { name: "settings_save" })

    await userEvent.selectOptions(
      screen.getByLabelText("settings_chunking_strategy_label", { selector: "select" }),
      "static",
    )
    await userEvent.click(screen.getByRole("button", { name: "settings_save" }))

    await waitFor(() => {
      expect(screen.getByRole("dialog", { name: "reingest_modal_title" })).toBeVisible()
    })
    expect(save).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole("button", { name: "reingest_skip" }))
    await waitFor(() => expect(save).toHaveBeenCalledOnce())
  })

  it("returns focus to Save when Escape dismisses the re-ingestion dialog", async () => {
    const ingest = createIngestionApi()
    vi.mocked(ingest.documents).mockResolvedValue({
      documents: [
        {
          doc_id: "doc-a",
          filename: "a.txt",
          chunks_count: 1,
          chunk_size: 512,
          chunk_overlap: 64,
          created_at: "2026-08-15T00:00:00Z",
          strategy: "recursive",
          schema_version: 1,
        },
      ],
      total: 1,
      next_cursor: null,
      truncated: false,
    })
    render(<SettingsPage ingestion={ingest} settings={createSettingsApi()} />)
    const saveButton = await screen.findByRole("button", { name: "settings_save" })
    await userEvent.selectOptions(
      screen.getByLabelText("settings_chunking_strategy_label", { selector: "select" }),
      "static",
    )
    await userEvent.click(saveButton)
    await screen.findByRole("dialog", { name: "reingest_modal_title" })

    await userEvent.keyboard("{Escape}")

    await waitFor(() => expect(saveButton).toHaveFocus())
    expect(screen.queryByRole("dialog", { name: "reingest_modal_title" })).not.toBeInTheDocument()
  })
})

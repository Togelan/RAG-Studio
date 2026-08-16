import { cleanup, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import type { TranslationKey } from "../../i18n/locale-inventory"
import "../../styles.css"
import { SettingsForm } from "./SettingsForm"
import type { SettingsDraft } from "./settings-api"
import "./settings.css"

afterEach(() => cleanup())

vi.mock("../../app/locale-provider", () => ({
  useLocaleContext: () => ({
    locale: "en",
    t: (key: TranslationKey) => key,
  }),
}))

const draft: SettingsDraft = {
  provider: "deepseek",
  model: "deepseek-chat",
  temperature: 1,
  max_tokens: 2048,
  system_prompt: "Answer from context.",
  top_k: 5,
  chunk_size: 512,
  chunk_overlap: 64,
  chunking: {
    schema_version: 1,
    strategy: "recursive",
    chunk_size: 512,
    chunk_overlap: 64,
    parent_size: 2048,
    window_sentences: 2,
  },
}

describe("SettingsForm", () => {
  it("renders a display-only masked credential and keeps unavailable providers disabled", () => {
    render(
      <SettingsForm
        apiKey=""
        draft={draft}
        keyIsStored
        models={["deepseek-chat"]}
        onApiKeyChange={vi.fn()}
        onDraftChange={vi.fn()}
        onRefreshModels={vi.fn()}
        onResetPrompt={vi.fn()}
      />,
    )

    const key = screen.getByLabelText("settings_api_key_label")
    expect(key).toHaveAttribute("type", "password")
    expect(key).toHaveValue("")
    expect(key).toHaveAttribute("placeholder", "••••••••")
    expect(screen.getByRole("option", { name: /OpenAI/u })).toBeDisabled()
    expect(screen.getByRole("option", { name: /Anthropic/u })).toBeDisabled()
    expect(screen.getByRole("option", { name: /Ollama/u })).toBeDisabled()
  })

  it("shows only controls for the active chunking strategy", () => {
    const parentDraft: SettingsDraft = {
      ...draft,
      chunking: { ...draft.chunking, strategy: "parent_document" },
    }
    render(
      <SettingsForm
        apiKey=""
        draft={parentDraft}
        keyIsStored={false}
        models={["deepseek-chat"]}
        onApiKeyChange={vi.fn()}
        onDraftChange={vi.fn()}
        onRefreshModels={vi.fn()}
        onResetPrompt={vi.fn()}
      />,
    )

    expect(screen.getByLabelText("settings_parent_size_label")).toBeVisible()
    expect(screen.queryByLabelText("settings_window_sentences_label")).not.toBeInTheDocument()
  })

  it("exposes the bounded temperature range with its live value in the label", () => {
    render(
      <SettingsForm
        apiKey=""
        draft={draft}
        keyIsStored={false}
        models={["deepseek-chat"]}
        onApiKeyChange={vi.fn()}
        onDraftChange={vi.fn()}
        onRefreshModels={vi.fn()}
        onResetPrompt={vi.fn()}
      />,
    )

    const temperature = screen.getByLabelText(/settings_temperature_label.*1\.00/u)
    expect(temperature).toHaveAttribute("min", "0")
    expect(temperature).toHaveAttribute("max", "2")
    expect(temperature).toHaveAttribute("step", "0.01")
  })

  it("renders Reset to default at the Settings touch-target size", () => {
    render(
      <SettingsForm
        apiKey=""
        draft={draft}
        keyIsStored={false}
        models={["deepseek-chat"]}
        onApiKeyChange={vi.fn()}
        onDraftChange={vi.fn()}
        onRefreshModels={vi.fn()}
        onResetPrompt={vi.fn()}
      />,
    )
    const reset = screen.getByRole("button", { name: "settings_reset_prompt" })
    expect(reset).toHaveClass("rs-settings-reset-prompt")
  })
})

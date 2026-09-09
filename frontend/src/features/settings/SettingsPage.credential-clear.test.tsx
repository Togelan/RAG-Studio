import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import type { TranslationKey } from "../../i18n/locale-inventory"
import { SettingsPage } from "./SettingsPage"
import {
  createIngestionApi,
  createSettingsApi,
  SETTINGS_FIXTURE,
} from "./SettingsPage.test-helpers"

vi.mock("../../app/locale-provider", () => ({
  useLocaleContext: () => ({
    locale: "en",
    t: (key: TranslationKey) => key,
  }),
}))

afterEach(() => cleanup())

describe("SettingsPage provider credential removal", () => {
  it("requires an explicit confirmation before a stored provider credential can be removed", async () => {
    // Given: the active provider has a masked stored credential.
    const clearCredential = vi.fn(() =>
      Promise.resolve({
        ...SETTINGS_FIXTURE,
        api_key: null,
      }),
    )
    const user = userEvent.setup()
    render(
      <SettingsPage
        ingestion={createIngestionApi()}
        settings={createSettingsApi({ clearCredential })}
      />,
    )

    // When: the user opens the credential removal action.
    await user.click(await screen.findByRole("button", { name: "settings_clear_stored_key" }))

    // Then: removal cannot occur until a confirmation dialog is shown.
    const confirm = await screen.findByRole("button", {
      name: "settings_clear_stored_key_confirm",
    })
    expect(clearCredential).not.toHaveBeenCalled()
    await user.click(confirm)
    await waitFor(() => expect(clearCredential).toHaveBeenCalledOnce())
    expect(
      screen.queryByRole("button", { name: "settings_clear_stored_key" }),
    ).not.toBeInTheDocument()
  })
})

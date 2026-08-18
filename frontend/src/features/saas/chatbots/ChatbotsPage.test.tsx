import { cleanup, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ApiError } from "../../../api/errors"
import { ChatbotsPage } from "./ChatbotsPage"
import type { ChatbotGateway, ChatbotRecord } from "./chatbots-api"

const workspaceId = "00000000-0000-4000-8000-000000000010"
const chatbotId = "00000000-0000-4000-8000-000000000020"

const supportBot: ChatbotRecord = {
  id: chatbotId,
  workspace_id: workspaceId,
  name: { en: "Support", ru: "Поддержка" },
  instructions: { en: "Use approved sources.", ru: "Используй разрешённые источники." },
  provider: "deepseek",
  model_name: "deepseek-chat",
  source_scope: "workspace_all",
  status: "enabled",
  version: 1,
}

function gateway(records: readonly ChatbotRecord[] = [supportBot]): ChatbotGateway {
  return {
    archive: vi.fn(() => Promise.resolve()),
    create: vi.fn((_workspaceId, input) =>
      Promise.resolve({ ...supportBot, ...input, id: chatbotId, version: 1 }),
    ),
    disable: vi.fn((_workspaceId, _chatbotId, version) =>
      Promise.resolve({ ...supportBot, status: "disabled" as const, version: version + 1 }),
    ),
    get: vi.fn(() => Promise.resolve(supportBot)),
    list: vi.fn(() => Promise.resolve(records)),
    update: vi.fn((_workspaceId, _chatbotId, input) =>
      Promise.resolve({ ...supportBot, ...input, version: input.version + 1 }),
    ),
  }
}

describe("Chatbot lifecycle UI", () => {
  afterEach(cleanup)

  it("creates a localized workspace chatbot from the empty state", async () => {
    // Given: an admin workspace with no chatbot definitions.
    const user = userEvent.setup()
    const api = gateway([])
    render(
      <ChatbotsPage gateway={api} locale="en" workspaceId={workspaceId} workspaceRole="admin" />,
    )

    // When: the admin completes the bilingual definition editor.
    await user.click(await screen.findByRole("button", { name: "New chatbot" }))
    await user.type(screen.getByLabelText("English name"), "Support")
    await user.type(screen.getByLabelText("Russian name"), "Поддержка")
    await user.type(screen.getByLabelText("English instructions"), "Use approved sources.")
    await user.type(
      screen.getByLabelText("Russian instructions"),
      "Используй разрешённые источники.",
    )
    await user.type(screen.getByLabelText("Provider"), "deepseek")
    await user.type(screen.getByLabelText("Model"), "deepseek-chat")
    await user.click(screen.getByRole("button", { name: "Create chatbot" }))

    // Then: the complete localized contract is sent and the created card is visible.
    expect(api.create).toHaveBeenCalledWith(
      workspaceId,
      expect.objectContaining({
        name: { en: "Support", ru: "Поддержка" },
        provider: "deepseek",
        model_name: "deepseek-chat",
        source_scope: "workspace_all",
      }),
    )
    expect(await screen.findByRole("heading", { name: "Support" })).toBeVisible()
  })

  it("uses server versions for edit, disable, and archive confirmations", async () => {
    // Given: an enabled chatbot visible to a workspace owner.
    const user = userEvent.setup()
    const api = gateway()
    render(
      <ChatbotsPage gateway={api} locale="en" workspaceId={workspaceId} workspaceRole="owner" />,
    )
    await screen.findByRole("heading", { name: "Support" })

    // When: the owner edits, disables, and then archives the current record.
    await user.click(screen.getByRole("button", { name: "Edit Support" }))
    await user.clear(screen.getByLabelText("English name"))
    await user.type(screen.getByLabelText("English name"), "Support desk")
    await user.click(screen.getByRole("button", { name: "Save changes" }))
    await user.click(await screen.findByRole("button", { name: "Disable Support desk" }))
    await user.click(screen.getByRole("button", { name: "Confirm disable" }))
    await user.click(await screen.findByRole("button", { name: "Delete Support desk" }))
    await user.click(screen.getByRole("button", { name: "Confirm delete" }))

    // Then: each mutation uses the latest server-confirmed version and archive removes the card.
    expect(api.update).toHaveBeenCalledWith(
      workspaceId,
      chatbotId,
      expect.objectContaining({ version: 1, name: { en: "Support desk", ru: "Поддержка" } }),
    )
    expect(api.disable).toHaveBeenCalledWith(workspaceId, chatbotId, 2)
    expect(api.archive).toHaveBeenCalledWith(workspaceId, chatbotId, 3)
    expect(screen.queryByRole("heading", { name: "Support desk" })).not.toBeInTheDocument()
  })

  it("keeps members read-only and surfaces a sanitized version conflict", async () => {
    // Given: one member view and one manager whose update conflicts with newer state.
    const user = userEvent.setup()
    const memberApi = gateway()
    const { unmount } = render(
      <ChatbotsPage
        gateway={memberApi}
        locale="en"
        workspaceId={workspaceId}
        workspaceRole="member"
      />,
    )
    await screen.findByRole("heading", { name: "Support" })

    // When: the member view is inspected and a manager later submits a stale version.
    expect(screen.queryByRole("button", { name: "New chatbot" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Edit Support" })).not.toBeInTheDocument()
    unmount()
    const managerApi = gateway()
    vi.mocked(managerApi.update).mockRejectedValue(
      new ApiError(409, "The request could not be completed.", null),
    )
    render(
      <ChatbotsPage
        gateway={managerApi}
        locale="en"
        workspaceId={workspaceId}
        workspaceRole="admin"
      />,
    )
    await user.click(await screen.findByRole("button", { name: "Edit Support" }))
    await user.click(screen.getByRole("button", { name: "Save changes" }))

    // Then: raw transport detail stays hidden and the user gets a reload-oriented conflict state.
    expect(
      await screen.findByText("This chatbot changed elsewhere. Reload it before editing again."),
    ).toBeVisible()
    expect(screen.queryByText("The request could not be completed.")).not.toBeInTheDocument()
  })

  it("keeps invalid localized configuration at its field before a mutation", async () => {
    // Given: an owner creating a chatbot with a whitespace-only English name.
    const user = userEvent.setup()
    const api = gateway([])
    render(
      <ChatbotsPage gateway={api} locale="en" workspaceId={workspaceId} workspaceRole="owner" />,
    )
    await user.click(await screen.findByRole("button", { name: "New chatbot" }))
    await user.type(screen.getByLabelText("English name"), "   ")
    await user.type(screen.getByLabelText("Russian name"), "Поддержка")
    await user.type(screen.getByLabelText("Provider"), "deepseek")
    await user.type(screen.getByLabelText("Model"), "deepseek-chat")

    // When: the owner submits the otherwise complete definition.
    await user.click(screen.getByRole("button", { name: "Create chatbot" }))

    // Then: a field-level explanation appears and no partial mutation is sent.
    expect(await screen.findByText("Enter an English name.")).toBeVisible()
    expect(api.create).not.toHaveBeenCalled()
  })
})

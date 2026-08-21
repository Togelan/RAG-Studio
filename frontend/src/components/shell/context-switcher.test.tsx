import { cleanup, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ContextSwitcher } from "./context-switcher"

afterEach(cleanup)

describe("ContextSwitcher", () => {
  it("labels the selected workspace and effective role without permanently showing Account", () => {
    render(
      <ContextSwitcher
        context={{
          accountName: "Northstar Account",
          availableContexts: [
            { id: "personal", kind: "personal" },
            { id: "workspace-a", kind: "workspace", name: "Research workspace", role: "owner" },
          ],
          selectedContextId: "workspace-a",
          state: "ready",
        }}
        locale="en"
      />,
    )

    expect(screen.queryByText("Account")).not.toBeInTheDocument()
    expect(screen.queryByText("Northstar Account")).not.toBeInTheDocument()
    expect(screen.getByLabelText("Context")).toHaveValue("workspace-a")
    expect(screen.getByTestId("active-context-label")).toHaveTextContent("Research workspace")
    expect(screen.getByText("Owner")).toBeVisible()
  })

  it("opens the compact context menu by keyboard with the selected role in its accessible name", async () => {
    const user = userEvent.setup()
    render(
      <ContextSwitcher
        compact
        context={{
          accountName: "Northstar Account",
          availableContexts: [
            { id: "personal", kind: "personal" },
            { id: "workspace-a", kind: "workspace", name: "Research workspace", role: "owner" },
          ],
          selectedContextId: "workspace-a",
          state: "ready",
        }}
        locale="en"
      />,
    )

    const trigger = screen.getByLabelText("Context: Research workspace, Owner")
    trigger.focus()
    await user.keyboard("{Enter}")
    expect(screen.getByLabelText("Context")).toHaveValue("workspace-a")
    expect(screen.getByTestId("active-context-label")).toHaveTextContent("Research workspace")
  })

  it("keeps the full active workspace name in a dedicated visible label", () => {
    const workspaceName = "International research workspace with a long visible name"
    render(
      <ContextSwitcher
        context={{
          accountName: "Northstar Account",
          availableContexts: [
            { id: "personal", kind: "personal" },
            { id: "workspace-a", kind: "workspace", name: workspaceName, role: "member" },
          ],
          selectedContextId: "workspace-a",
          state: "ready",
        }}
        locale="en"
      />,
    )

    expect(screen.getByTestId("active-context-label")).toHaveTextContent(workspaceName)
  })

  it("clears selected workspace identity in revoked and forbidden states", () => {
    const { rerender } = render(
      <ContextSwitcher
        context={{
          accountName: "Northstar Account",
          availableContexts: [
            { id: "workspace-a", kind: "workspace", name: "Private notes", role: "admin" },
          ],
          selectedContextId: "workspace-a",
          state: "ready",
        }}
        locale="en"
      />,
    )
    expect(screen.getByTestId("active-context-label")).toHaveTextContent("Private notes")

    rerender(
      <ContextSwitcher
        context={{
          accountName: "Northstar Account",
          state: "revoked",
        }}
        locale="en"
      />,
    )

    expect(screen.queryByText("Private notes")).not.toBeInTheDocument()
    expect(screen.queryByText("Admin")).not.toBeInTheDocument()
    expect(screen.getByRole("status")).toHaveTextContent("no longer available")
  })

  it("does not expose a prior selection while a new server selection is pending", () => {
    render(
      <ContextSwitcher
        context={{
          accountName: "Northstar Account",
          state: "selection-pending",
        }}
        locale="en"
      />,
    )

    expect(screen.getByRole("status")).toHaveTextContent("Updating context")
  })

  it("offers only server-confirmed recovery contexts after revocation", async () => {
    const user = userEvent.setup()
    const onSelectContext = vi.fn()
    render(
      <ContextSwitcher
        context={{
          accountName: "Northstar Account",
          availableContexts: [
            { id: "personal", kind: "personal" },
            {
              id: "workspace-b",
              kind: "workspace",
              name: "Безопасное пространство",
              role: "member",
            },
          ],
          onSelectContext,
          state: "revoked",
        }}
        locale="ru"
      />,
    )

    expect(screen.queryByText("Private notes")).not.toBeInTheDocument()
    expect(screen.queryByText("Администратор")).not.toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText("Выберите доступный контекст"), "workspace-b")
    expect(onSelectContext).toHaveBeenCalledWith("workspace-b")
  })

  it("exposes an injected sign-in recovery action when no context is available", async () => {
    const user = userEvent.setup()
    const onSignIn = vi.fn()
    render(<ContextSwitcher context={{ onSignIn, state: "no-context" }} locale="en" />)

    await user.click(screen.getByRole("button", { name: "Sign in" }))
    expect(onSignIn).toHaveBeenCalledOnce()
  })

  it("only submits a context choice through the injected authority callback", async () => {
    const user = userEvent.setup()
    const onSelectContext = vi.fn()
    render(
      <ContextSwitcher
        context={{
          accountName: "Northstar Account",
          availableContexts: [
            { id: "personal", kind: "personal" },
            { id: "workspace-a", kind: "workspace", name: "Research", role: "member" },
          ],
          onSelectContext,
          selectedContextId: "personal",
          state: "ready",
        }}
        locale="ru"
      />,
    )

    await user.selectOptions(screen.getByLabelText("Контекст"), "workspace-a")
    expect(onSelectContext).toHaveBeenCalledWith("workspace-a")
    expect(screen.getByTestId("active-context-label")).toHaveTextContent("Личная лаборатория")
  })
})

import { cleanup, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { afterEach, describe, expect, it, vi } from "vitest"

import { AuthPage } from "./auth/AuthPage"
import { SaasShell } from "./shell/SaasShell"

afterEach(cleanup)

describe("Stage 3 authentication and workspace shell", () => {
  it("submits recoverable sign-in credentials without rendering browser auth state", async () => {
    // Given: an unauthenticated user on the English sign-in surface.
    const user = userEvent.setup()
    const onAuthenticate = vi.fn(() => Promise.resolve())
    render(
      <AuthPage
        locale="en"
        mode="sign-in"
        onAuthenticate={onAuthenticate}
        onModeChange={vi.fn()}
        status={{ kind: "ready" }}
      />,
    )

    // When: valid credentials are submitted.
    await user.type(screen.getByLabelText("Email"), "owner@example.test")
    await user.type(screen.getByLabelText("Password"), "correct-horse")
    await user.click(screen.getByRole("button", { name: "Sign in" }))

    // Then: only the credential command crosses the component boundary.
    expect(onAuthenticate).toHaveBeenCalledWith({
      email: "owner@example.test",
      password: "correct-horse",
    })
    expect(document.body.textContent).not.toMatch(/csrf|session token|bearer/iu)
  })

  it("exposes owner controls and switches only after a confirmed workspace selection", async () => {
    // Given: an owner with two authoritative workspace memberships.
    const user = userEvent.setup()
    const onSelectWorkspace = vi.fn(() => Promise.resolve())
    render(
      <MemoryRouter initialEntries={["/saas"]}>
        <SaasShell
          activeWorkspaceId="00000000-0000-4000-8000-000000000010"
          email="owner@example.test"
          locale="en"
          onSelectWorkspace={onSelectWorkspace}
          onSignOut={vi.fn(() => Promise.resolve())}
          workspaceRole="owner"
          workspaces={[
            {
              id: "00000000-0000-4000-8000-000000000010",
              name: "Acme Knowledge",
              role: "owner",
            },
            {
              id: "00000000-0000-4000-8000-000000000011",
              name: "Research Lab",
              role: "member",
            },
          ]}
        >
          <p>Workspace content</p>
        </SaasShell>
      </MemoryRouter>,
    )

    // When: the second workspace is selected.
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Active workspace" }),
      "00000000-0000-4000-8000-000000000011",
    )

    // Then: the BFF selection callback runs and owner-only navigation is visible.
    expect(onSelectWorkspace).toHaveBeenCalledWith("00000000-0000-4000-8000-000000000011")
    expect(screen.getByRole("link", { name: "People & invitations" })).toBeVisible()
    expect(screen.getByText("Owner")).toBeVisible()
  })

  it("omits management controls for a member while retaining chatbot access", () => {
    // Given: a member in one selected workspace.
    render(
      <MemoryRouter initialEntries={["/saas"]}>
        <SaasShell
          activeWorkspaceId="00000000-0000-4000-8000-000000000010"
          email="member@example.test"
          locale="en"
          onSelectWorkspace={vi.fn(() => Promise.resolve())}
          onSignOut={vi.fn(() => Promise.resolve())}
          workspaceRole="member"
          workspaces={[
            {
              id: "00000000-0000-4000-8000-000000000010",
              name: "Acme Knowledge",
              role: "member",
            },
          ]}
        >
          <p>Workspace content</p>
        </SaasShell>
      </MemoryRouter>,
    )

    // When: the member workspace shell renders.
    const chatbotLink = screen.getByRole("link", { name: "Chatbots" })

    // Then: test access remains, while management destinations are absent.
    expect(chatbotLink).toBeVisible()
    expect(screen.queryByRole("link", { name: "People & invitations" })).not.toBeInTheDocument()
    expect(screen.getByText("Member")).toBeVisible()
  })

  it("keeps compact navigation inaccessible until its drawer opens", async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={["/saas"]}>
        <SaasShell
          activeWorkspaceId="00000000-0000-4000-8000-000000000010"
          email="owner@example.test"
          locale="en"
          onSelectWorkspace={vi.fn(() => Promise.resolve())}
          onSignOut={vi.fn(() => Promise.resolve())}
          workspaceRole="owner"
          workspaces={[{ id: "00000000-0000-4000-8000-000000000010", name: "Acme", role: "owner" }]}
        >
          <p>Workspace content</p>
        </SaasShell>
      </MemoryRouter>,
    )

    expect(screen.getAllByRole("link", { name: "Sources" })).toHaveLength(1)
    await user.click(screen.getByRole("button", { name: "Navigation" }))
    expect(screen.getByRole("dialog", { name: "Navigation" })).toBeVisible()
    await user.keyboard("{Escape}")
    expect(screen.queryByRole("dialog", { name: "Navigation" })).toBeNull()
    expect(screen.getAllByRole("link", { name: "Sources" })).toHaveLength(1)
  })
})

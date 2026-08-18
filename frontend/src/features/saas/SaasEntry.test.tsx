import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { afterEach, describe, expect, it, vi } from "vitest"
import { apiClient } from "../../api/client"
import { ApiError } from "../../api/errors"
import type { AuthGateway, AuthSession } from "./auth/auth-api"
import { SaasEntry } from "./SaasEntry"
import type { WorkspaceGateway } from "./workspaces/workspace-api"

const ownerSession: AuthSession = {
  user_id: "00000000-0000-4000-8000-000000000001",
  email: "owner@example.test",
  workspace: {
    id: "00000000-0000-4000-8000-000000000010",
    role: "owner",
  },
}

function authGateway(): AuthGateway {
  return {
    getSession: vi.fn(() =>
      Promise.reject(
        new ApiError(401, "The request could not be completed. Please try again.", null),
      ),
    ),
    refresh: vi.fn(() => Promise.resolve(ownerSession)),
    selectWorkspace: vi.fn(() => Promise.resolve(ownerSession)),
    signIn: vi.fn(() => Promise.resolve({ ...ownerSession, workspace: null })),
    signOut: vi.fn(() => Promise.resolve()),
    signUp: vi.fn(() => Promise.resolve({ confirmation_required: false })),
  }
}

describe("SaaS entry integration", () => {
  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  it("runs unauthenticated session recovery once across auth form rerenders", async () => {
    // Given: the default auth gateway receives an unauthenticated session response.
    const user = userEvent.setup()
    const get = vi
      .spyOn(apiClient, "get")
      .mockRejectedValue(new ApiError(401, "The request could not be completed.", null))
    render(
      <MemoryRouter initialEntries={["/saas"]}>
        <SaasEntry locale="en" />
      </MemoryRouter>,
    )

    // When: the auth screen renders and the user changes its local mode.
    await user.click(await screen.findByRole("button", { name: "Create account" }))

    // Then: rerendering the form does not restart session recovery or replace its status.
    await waitFor(() => expect(get).toHaveBeenCalledOnce())
  })

  it("recovers from an expired session and reaches the trusted workspace shell", async () => {
    // Given: an expired BFF session and an account with no workspace yet.
    const user = userEvent.setup()
    const auth = authGateway()
    const workspace: WorkspaceGateway = {
      create: vi.fn(() =>
        Promise.resolve({
          id: "00000000-0000-4000-8000-000000000010",
          name: "Acme Knowledge",
          role: "owner" as const,
        }),
      ),
      list: vi.fn(() => Promise.resolve([])),
    }
    render(
      <MemoryRouter initialEntries={["/saas"]}>
        <SaasEntry authGateway={auth} locale="en" workspaceGateway={workspace} />
      </MemoryRouter>,
    )

    // When: the user signs in and creates the first workspace.
    await user.type(await screen.findByLabelText("Email"), "owner@example.test")
    await user.type(screen.getByLabelText("Password"), "correct-horse")
    await user.click(screen.getByRole("button", { name: "Sign in" }))
    await user.type(await screen.findByLabelText("Workspace name"), "Acme Knowledge")
    await user.click(screen.getByRole("button", { name: "Create workspace" }))

    // Then: server-confirmed workspace context drives the visible shell.
    expect(await screen.findByRole("combobox", { name: "Active workspace" })).toHaveValue(
      "00000000-0000-4000-8000-000000000010",
    )
    expect(screen.getByText("Owner")).toBeVisible()
    expect(auth.selectWorkspace).toHaveBeenCalledWith("00000000-0000-4000-8000-000000000010")
  })

  it("selects the only existing workspace after a new sign-in session has no active selection", async () => {
    // Given: an existing owner workspace and a fresh BFF sign-in session without a selected workspace.
    const user = userEvent.setup()
    const auth = authGateway()
    const workspace: WorkspaceGateway = {
      create: vi.fn(),
      list: vi.fn(() =>
        Promise.resolve([
          {
            id: "00000000-0000-4000-8000-000000000010",
            name: "Acme Knowledge",
            role: "owner" as const,
          },
        ]),
      ),
    }
    render(
      <MemoryRouter initialEntries={["/saas"]}>
        <SaasEntry authGateway={auth} locale="en" workspaceGateway={workspace} />
      </MemoryRouter>,
    )

    // When: the owner signs in again after signing out.
    await user.type(await screen.findByLabelText("Email"), "owner@example.test")
    await user.type(screen.getByLabelText("Password"), "correct-horse")
    await user.click(screen.getByRole("button", { name: "Sign in" }))

    // Then: the existing workspace becomes the BFF-selected context instead of rendering new-workspace setup.
    expect(await screen.findByRole("combobox", { name: "Active workspace" })).toHaveValue(
      "00000000-0000-4000-8000-000000000010",
    )
    expect(auth.selectWorkspace).toHaveBeenCalledWith("00000000-0000-4000-8000-000000000010")
    expect(screen.queryByRole("button", { name: "Create workspace" })).not.toBeInTheDocument()
  })
})

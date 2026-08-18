import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"
import { PeoplePage } from "./PeoplePage"
import type { PeopleGateway } from "./people-api"

const workspaceId = "00000000-0000-4000-8000-000000000010"

function gateway(): PeopleGateway {
  return {
    changeMembership: vi.fn(),
    createInvitation: vi.fn(() =>
      Promise.resolve({
        id: "00000000-0000-4000-8000-000000000030",
        email: "teammate@example.test",
        role: "admin" as const,
        status: "pending",
        expires_at: "2026-08-24T10:00:00Z",
      }),
    ),
    listInvitations: vi.fn(() => Promise.resolve([])),
    listMembers: vi.fn(() =>
      Promise.resolve([
        { user_id: "00000000-0000-4000-8000-000000000001", role: "owner" as const },
        { user_id: "00000000-0000-4000-8000-000000000002", role: "member" as const },
      ]),
    ),
    revokeInvitation: vi.fn(() => Promise.resolve()),
    revokeMembership: vi.fn(() => Promise.resolve()),
  }
}

describe("People and invitations", () => {
  afterEach(cleanup)

  it("lets an owner load members and create an invitation", async () => {
    // Given: an owner workspace with active members and no pending invitations.
    const user = userEvent.setup()
    const api = gateway()
    render(<PeoplePage gateway={api} locale="en" workspaceId={workspaceId} workspaceRole="owner" />)

    // When: the owner invites an administrator.
    await screen.findByText("00000000-0000-4000-8000-000000000002")
    await user.type(screen.getByLabelText("Email address"), "teammate@example.test")
    await user.selectOptions(screen.getByLabelText("Workspace role"), "admin")
    await user.click(screen.getByRole("button", { name: "Send invitation" }))

    // Then: the typed gateway receives the scoped mutation and its response is rendered.
    expect(api.createInvitation).toHaveBeenCalledWith(workspaceId, {
      email: "teammate@example.test",
      role: "admin",
    })
    expect(await screen.findByText("teammate@example.test")).toBeVisible()
  })

  it("shows admins invitation controls without requesting owner-only members", async () => {
    // Given: an admin with one pending invitation.
    const api = gateway()
    vi.mocked(api.listInvitations).mockResolvedValue([
      {
        id: "00000000-0000-4000-8000-000000000031",
        email: "pending@example.test",
        role: "member",
        status: "pending",
        expires_at: null,
      },
    ])

    // When: the admin opens People and invitations.
    render(<PeoplePage gateway={api} locale="en" workspaceId={workspaceId} workspaceRole="admin" />)

    // Then: invitations load, owner-only member data does not, and the boundary is explained.
    expect(await screen.findByText("pending@example.test")).toBeVisible()
    expect(api.listMembers).not.toHaveBeenCalled()
    expect(screen.getByText("Only workspace owners can manage member roles.")).toBeVisible()
    expect(screen.getByRole("button", { name: "Send invitation" })).toBeVisible()
  })

  it("keeps member access local and does not call management endpoints", async () => {
    // Given: a member who navigates directly to the management URL.
    const api = gateway()

    // When: the People screen evaluates the trusted workspace role.
    render(
      <PeoplePage gateway={api} locale="en" workspaceId={workspaceId} workspaceRole="member" />,
    )

    // Then: no management endpoint is called and no mutation control is exposed.
    await waitFor(() => expect(api.listInvitations).not.toHaveBeenCalled())
    expect(api.listMembers).not.toHaveBeenCalled()
    expect(screen.getByText("You do not have permission to manage this workspace.")).toBeVisible()
    expect(screen.queryByRole("button", { name: "Send invitation" })).not.toBeInTheDocument()
  })
})

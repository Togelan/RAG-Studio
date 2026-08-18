import { cleanup, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { WorkspaceLifecyclePanel } from "./WorkspaceLifecyclePanel"
import type { WorkspaceLifecycleGateway } from "./workspace-lifecycle-api"

const workspaceId = "00000000-0000-4000-8000-000000000010"
const workspaceName = "Transfer archive verification"
const targetUserId = "00000000-0000-4000-8000-000000000002"
const memberUserId = "00000000-0000-4000-8000-000000000003"

function gateway(): WorkspaceLifecycleGateway {
  return {
    acceptInvitation: vi.fn(),
    archiveWorkspace: vi.fn(() => Promise.resolve()),
    listMembers: vi.fn(() =>
      Promise.resolve([
        { user_id: "00000000-0000-4000-8000-000000000001", role: "owner" as const },
        { user_id: targetUserId, role: "admin" as const },
        { user_id: memberUserId, role: "member" as const },
      ]),
    ),
    transferOwnership: vi.fn(() => Promise.resolve()),
  }
}

describe("Workspace lifecycle panel", () => {
  afterEach(cleanup)

  it("requires explicit owner confirmations before transferring or archiving a workspace", async () => {
    // Given: an owner with an eligible administrator and a safe lifecycle gateway.
    const user = userEvent.setup()
    const api = gateway()
    const onArchived = vi.fn()
    const onTransferred = vi.fn()
    render(
      <WorkspaceLifecyclePanel
        gateway={api}
        locale="en"
        onArchived={onArchived}
        onTransferred={onTransferred}
        workspaceId={workspaceId}
        workspaceName={workspaceName}
        workspaceRole="owner"
      />,
    )

    // When: the owner transfers the workspace to the selected administrator and confirms it.
    await user.selectOptions(await screen.findByLabelText("New owner"), targetUserId)
    await user.click(screen.getByRole("button", { name: "Transfer ownership" }))
    expect(screen.getByText(targetUserId)).toBeVisible()
    expect(api.transferOwnership).not.toHaveBeenCalled()
    await user.click(screen.getByRole("button", { name: "Confirm transfer" }))

    // Then: the scoped gateway receives only the selected member after confirmation.
    expect(api.transferOwnership).toHaveBeenCalledWith(workspaceId, targetUserId)
    expect(onTransferred).toHaveBeenCalledOnce()

    // When: the owner opens archive confirmation, cancels, then confirms.
    await user.click(screen.getByRole("button", { name: "Archive workspace" }))
    expect(screen.getByText(new RegExp(workspaceName))).toBeVisible()
    await user.click(screen.getByRole("button", { name: "Cancel" }))
    expect(api.archiveWorkspace).not.toHaveBeenCalled()
    await user.click(screen.getByRole("button", { name: "Archive workspace" }))
    await user.click(screen.getByRole("button", { name: "Confirm archive" }))

    // Then: archive runs only after confirmation and the active workspace boundary is cleared.
    expect(api.archiveWorkspace).toHaveBeenCalledWith(workspaceId)
    expect(onArchived).toHaveBeenCalledOnce()
  })

  it("does not expose owner lifecycle controls to an administrator", () => {
    // Given: an administrator viewing a workspace they do not own.
    const api = gateway()
    render(
      <WorkspaceLifecyclePanel
        gateway={api}
        locale="en"
        onArchived={vi.fn()}
        onTransferred={vi.fn()}
        workspaceId={workspaceId}
        workspaceName={workspaceName}
        workspaceRole="admin"
      />,
    )

    // When: the panel evaluates the server-confirmed role.

    // Then: no privileged data request or lifecycle action is exposed.
    expect(api.listMembers).not.toHaveBeenCalled()
    expect(screen.queryByRole("button", { name: "Transfer ownership" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Archive workspace" })).not.toBeInTheDocument()
  })

  it("keeps lifecycle guidance singular while member data is loading", () => {
    const pendingMembers = new Promise<never>(() => undefined)
    const api: WorkspaceLifecycleGateway = {
      ...gateway(),
      listMembers: vi.fn(() => pendingMembers),
    }
    render(
      <WorkspaceLifecyclePanel
        gateway={api}
        locale="en"
        onArchived={vi.fn()}
        onTransferred={vi.fn()}
        workspaceId={workspaceId}
        workspaceName={workspaceName}
        workspaceRole="owner"
      />,
    )

    expect(screen.getAllByText("Transfer ownership before archiving a workspace.")).toHaveLength(1)
  })

  it("offers ownership transfer only to active administrators", async () => {
    const api = gateway()
    render(
      <WorkspaceLifecyclePanel
        gateway={api}
        locale="en"
        onArchived={vi.fn()}
        onTransferred={vi.fn()}
        workspaceId={workspaceId}
        workspaceName={workspaceName}
        workspaceRole="owner"
      />,
    )

    expect(await screen.findByRole("option", { name: targetUserId })).toBeVisible()
    expect(screen.queryByRole("option", { name: memberUserId })).not.toBeInTheDocument()
  })
})

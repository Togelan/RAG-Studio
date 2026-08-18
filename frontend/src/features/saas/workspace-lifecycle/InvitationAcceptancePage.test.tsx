import { cleanup, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { InvitationAcceptancePage } from "./InvitationAcceptancePage"
import type { WorkspaceLifecycleGateway } from "./workspace-lifecycle-api"

const invitationToken = "token-token-token-token-token-token-token-token-token"
const workspace = {
  id: "00000000-0000-4000-8000-000000000010",
  name: "Acme Knowledge",
  role: "member" as const,
}

function gateway(): WorkspaceLifecycleGateway {
  return {
    acceptInvitation: vi.fn(() => Promise.resolve(workspace)),
    archiveWorkspace: vi.fn(),
    listMembers: vi.fn(),
    transferOwnership: vi.fn(),
  }
}

describe("Invitation acceptance", () => {
  afterEach(cleanup)

  it("accepts the invitation token and hands the trusted workspace response to the entry route", async () => {
    // Given: a signed-in user arriving from a local invitation link with its opaque token.
    const user = userEvent.setup()
    const api = gateway()
    const onAccepted = vi.fn()
    render(
      <InvitationAcceptancePage
        gateway={api}
        initialToken={invitationToken}
        locale="en"
        onAccepted={onAccepted}
      />,
    )

    // When: the user accepts the invitation.
    await user.click(screen.getByRole("button", { name: "Accept invitation" }))

    // Then: the opaque token is sent to the BFF and the route receives only its workspace result.
    expect(api.acceptInvitation).toHaveBeenCalledWith(invitationToken)
    expect(onAccepted).toHaveBeenCalledWith(workspace)
  })

  it("keeps a selected-workspace failure recoverable without rendering a raw error", async () => {
    // Given: the BFF accepts the token but the active-workspace session update fails.
    const user = userEvent.setup()
    const api = gateway()
    const onAccepted = vi.fn(() => Promise.reject(new Error("internal provider detail")))
    render(
      <InvitationAcceptancePage
        gateway={api}
        initialToken={invitationToken}
        locale="en"
        onAccepted={onAccepted}
      />,
    )

    // When: the user accepts the invitation.
    await user.click(screen.getByRole("button", { name: "Accept invitation" }))

    // Then: the page exposes the safe retry message and never the raw failure.
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The workspace change could not be completed. Please try again.",
    )
    expect(screen.queryByText("internal provider detail")).not.toBeInTheDocument()
  })
})

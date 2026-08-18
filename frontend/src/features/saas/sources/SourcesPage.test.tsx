import { cleanup, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { SourcesPage } from "./SourcesPage"
import type { SourceDocument, SourcesGateway } from "./sources-api"

const workspaceId = "00000000-0000-4000-8000-000000000010"
const sourceDocument: SourceDocument = {
  chunk_count: 1,
  created_at: "2026-08-18T08:00:00Z",
  doc_id: "document-id",
  filename: "handbook.md",
}

function gateway(documents: readonly SourceDocument[] = []): SourcesGateway {
  return {
    list: vi.fn(() => Promise.resolve(documents)),
    remove: vi.fn(() => Promise.resolve()),
    upload: vi.fn(() => Promise.resolve()),
  }
}

describe("Source Library", () => {
  afterEach(cleanup)

  it("uploads and re-renders an authorized workspace source", async () => {
    // Given: an admin opens an empty source library.
    const user = userEvent.setup()
    const api = gateway([sourceDocument])
    render(
      <SourcesPage gateway={api} locale="en" workspaceId={workspaceId} workspaceRole="admin" />,
    )

    // When: the admin selects one supported source and submits the upload form.
    const file = new File(["Source-backed answer evidence."], "handbook.md", {
      type: "text/markdown",
    })
    await user.upload(await screen.findByLabelText("Source file"), file)
    await user.click(screen.getByRole("button", { name: "Upload source" }))

    // Then: the scoped gateway receives the file and the library renders its source record.
    expect(api.upload).toHaveBeenCalledWith(workspaceId, file)
    expect(await screen.findByText("handbook.md")).toBeVisible()
  })

  it("keeps member source management permission-honest", async () => {
    // Given: a member enters the source URL directly.
    const api = gateway([sourceDocument])
    render(
      <SourcesPage gateway={api} locale="en" workspaceId={workspaceId} workspaceRole="member" />,
    )

    // When: the page evaluates the server-confirmed role.
    // Then: no source operation starts and the unavailable task is explained.
    expect(api.list).not.toHaveBeenCalled()
    expect(screen.getByText("You do not have permission to manage sources.")).toBeVisible()
    expect(screen.queryByRole("button", { name: "Upload source" })).not.toBeInTheDocument()
  })

  it("requires confirmation before an authorized source removal", async () => {
    // Given: an owner sees one indexed source.
    const user = userEvent.setup()
    const api = gateway([sourceDocument])
    render(
      <SourcesPage gateway={api} locale="en" workspaceId={workspaceId} workspaceRole="owner" />,
    )

    // When: the owner requests and confirms source removal.
    await user.click(await screen.findByRole("button", { name: "Remove handbook.md" }))
    expect(screen.getByText("Remove source?")).toBeVisible()
    await user.click(screen.getByRole("button", { name: "Confirm removal" }))

    // Then: the typed gateway receives only the document identifier and the row leaves the library.
    expect(api.remove).toHaveBeenCalledWith(workspaceId, "document-id")
    expect(screen.queryByText("handbook.md")).not.toBeInTheDocument()
  })
})

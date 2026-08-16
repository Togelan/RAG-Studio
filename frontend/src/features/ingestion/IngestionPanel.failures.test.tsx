import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ApiError } from "../../api/errors"
import type { TranslationKey } from "../../i18n/locale-inventory"
import { IngestionPanel } from "./IngestionPanel"
import type { IngestionApi } from "./ingestion-api"

vi.mock("../../app/locale-provider", () => ({
  useLocaleContext: () => ({
    locale: "en",
    t: (key: TranslationKey) => key,
    format: (key: TranslationKey, values: { readonly count?: number; readonly name?: string }) =>
      `${key}:${values.count ?? values.name}`,
  }),
}))

afterEach(() => cleanup())

const document = {
  doc_id: "doc-1",
  filename: "preserved.txt",
  chunks_count: 1,
  chunk_size: 512,
  chunk_overlap: 64,
  created_at: "2026-08-15T00:00:00Z",
  strategy: "recursive",
  schema_version: 1,
} as const

function api(overrides: Partial<IngestionApi> = {}): IngestionApi {
  return {
    chunks: vi.fn(() => Promise.resolve({ chunks: [], next_cursor: null, truncated: false })),
    clear: vi.fn(() =>
      Promise.resolve({ status: "ok" as const, message: "cleared", deleted_count: 1 }),
    ),
    deleteDocument: vi.fn(() =>
      Promise.resolve({ status: "ok" as const, message: "deleted", deleted_count: 1 }),
    ),
    documents: vi.fn(() =>
      Promise.resolve({ documents: [document], total: 1, next_cursor: null, truncated: false }),
    ),
    progress: vi.fn(() =>
      Promise.resolve({
        file_id: "job",
        status: "done" as const,
        message: "ready",
        chunks_count: 1,
      }),
    ),
    reingest: vi.fn(() =>
      Promise.resolve({ status: "processing" as const, file_id: "job", message: "queued" }),
    ),
    upload: vi.fn(() =>
      Promise.resolve({
        kind: "accepted" as const,
        response: { status: "unchanged" as const, file_id: "", message: "unchanged" },
      }),
    ),
    ...overrides,
  }
}

describe("IngestionPanel bounded failures", () => {
  it("keeps the document visible when chunk preview fails and never renders the raw error", async () => {
    const hostile = "provider /private/path secret"
    render(
      <IngestionPanel
        api={api({ chunks: vi.fn(() => Promise.reject(new Error(hostile))) })}
        refreshToken={0}
      />,
    )
    await screen.findByText("preserved.txt")

    await userEvent.click(screen.getByRole("button", { name: "settings_doc_col_chunks" }))

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "ingestion_chunk_preview_unavailable",
    )
    expect(screen.getByText("preserved.txt")).toBeVisible()
    expect(screen.queryByText(hostile)).not.toBeInTheDocument()
  })

  it.each(["delete", "clear"] as const)(
    "preserves the old document and sanitizes a failed %s mutation",
    async (operation) => {
      const hostile = "provider /private/path secret"
      const remove = vi.fn(() => Promise.reject(new Error(hostile)))
      render(
        <IngestionPanel
          api={api(operation === "delete" ? { deleteDocument: remove } : { clear: remove })}
          refreshToken={0}
        />,
      )
      await screen.findByText("preserved.txt")

      if (operation === "delete") {
        await userEvent.click(
          screen.getByRole("button", { name: "ingestion_delete_document_aria:preserved.txt" }),
        )
        const dialog = screen.getByRole("dialog", { name: "ingestion_delete_document_title" })
        await userEvent.click(within(dialog).getByRole("button", { name: "settings_delete" }))
      } else {
        await userEvent.click(screen.getByRole("button", { name: "ingestion_clear_all" }))
        const dialog = screen.getByRole("dialog", { name: "ingestion_clear_all_title" })
        await userEvent.click(within(dialog).getByRole("button", { name: "ingestion_clear_all" }))
      }

      expect(await screen.findByRole("alert")).toHaveTextContent(
        "The document request could not be completed. Please try again.",
      )
      expect(screen.getByText("preserved.txt")).toBeVisible()
      expect(screen.queryByText(hostile)).not.toBeInTheDocument()
      expect(remove).toHaveBeenCalledOnce()
    },
  )

  it.each([400, 422, 429, 503])(
    "renders a sanitized upload status %s without retry",
    async (status) => {
      const upload = vi.fn(() =>
        Promise.reject(new ApiError(status, `safe status ${status}`, null)),
      )
      render(<IngestionPanel api={api({ upload })} refreshToken={0} />)
      await screen.findByText("preserved.txt")

      fireEvent.change(screen.getByLabelText("settings_browse_files"), {
        target: { files: [new File(["safe"], "failed.txt", { type: "text/plain" })] },
      })

      expect(await screen.findByText("ingestion_progress_unavailable")).toBeVisible()
      expect(screen.queryByText(`safe status ${status}`)).not.toBeInTheDocument()
      expect(upload).toHaveBeenCalledOnce()
    },
  )

  it("aborts an active upload poll and removes its timer on unmount", async () => {
    const upload = vi.fn<IngestionApi["upload"]>(() =>
      Promise.resolve({
        kind: "accepted" as const,
        response: { status: "processing" as const, file_id: "job", message: "queued" },
      }),
    )
    const view = render(<IngestionPanel api={api({ upload })} refreshToken={0} />)
    await screen.findByText("preserved.txt")
    fireEvent.change(screen.getByLabelText("settings_browse_files"), {
      target: { files: [new File(["safe"], "pending.txt", { type: "text/plain" })] },
    })
    await waitFor(() => expect(upload).toHaveBeenCalledOnce())
    const signal = vi.mocked(upload).mock.calls[0]?.[2]

    view.unmount()

    expect(signal?.aborted).toBe(true)
  })
})

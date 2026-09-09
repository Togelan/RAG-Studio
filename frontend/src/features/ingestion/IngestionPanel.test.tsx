import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import type { TranslationKey } from "../../i18n/locale-inventory"
import { IngestionPanel } from "./IngestionPanel"
import type { IngestionApi } from "./ingestion-api"

afterEach(() => cleanup())

vi.mock("../../app/locale-provider", () => ({
  useLocaleContext: () => ({
    locale: "en",
    t: (key: TranslationKey) => key,
    format: (key: TranslationKey, values: { readonly count?: number; readonly name?: string }) =>
      `${key}:${values.count ?? values.name}`,
  }),
}))

function emptyApi(overrides: Partial<IngestionApi> = {}): IngestionApi {
  return {
    chunks: vi.fn(() => Promise.resolve({ chunks: [], next_cursor: null, truncated: false })),
    clear: vi.fn(() =>
      Promise.resolve({ status: "ok" as const, message: "cleared", deleted_count: 0 }),
    ),
    deleteDocument: vi.fn(() =>
      Promise.resolve({ status: "ok" as const, message: "deleted", deleted_count: 1 }),
    ),
    documents: vi.fn(() =>
      Promise.resolve({ documents: [], total: 0, next_cursor: null, truncated: false }),
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

interface FileSystemModule {
  readFileSync(path: string, encoding: "utf8"): string
}

describe("IngestionPanel", () => {
  it("exposes Browse files through a native file-control label", () => {
    render(<IngestionPanel api={emptyApi()} refreshToken={0} />)

    const input = screen.getByLabelText("settings_browse_files") as HTMLInputElement
    expect(input.type).toBe("file")
    expect(input.labels).toHaveLength(1)
    expect(input.labels?.[0]).toHaveTextContent("settings_browse_files")
  })

  it("renders document and clear actions at the ingestion touch-target size", async () => {
    const api = emptyApi({
      documents: vi.fn(() =>
        Promise.resolve({
          documents: [
            {
              doc_id: "doc-1",
              filename: "records.csv",
              chunks_count: 1,
              chunk_size: 512,
              chunk_overlap: 64,
              created_at: "2026-08-15T00:00:00Z",
              strategy: "csv_row",
              schema_version: 1,
            },
          ],
          total: 1,
          next_cursor: null,
          truncated: false,
        }),
      ),
    })
    render(<IngestionPanel api={api} refreshToken={0} />)

    expect(await screen.findByRole("button", { name: "ingestion_clear_all" })).toHaveClass(
      "rs-ingestion-clear-all",
    )
    expect(screen.getByRole("button", { name: "settings_doc_col_chunks" })).toHaveClass(
      "rs-document-chunks-toggle",
    )
    const moduleName = ["node", "fs"].join(":")
    const fileSystem = (await import(moduleName)) as unknown as FileSystemModule
    const styles = fileSystem.readFileSync("src/features/ingestion/ingestion.css", "utf8")
    expect(styles).toMatch(
      /\.rs-button\.rs-ingestion-clear-all[^}]*\.rs-button\.rs-document-chunks-toggle\s*\{[^}]*min-height:\s*var\(--rs-space-44\)/u,
    )
  })

  it("keeps a long document identity and its actions inside the Knowledge card", async () => {
    const filename = `${"long-unbroken-document-name-".repeat(8)}.pdf`
    const api = emptyApi({
      documents: vi.fn(() =>
        Promise.resolve({
          documents: [
            {
              doc_id: "doc-long",
              filename,
              chunks_count: 154,
              chunk_size: 512,
              chunk_overlap: 64,
              created_at: "2026-08-26T00:00:00Z",
              strategy: "sentence_window",
              schema_version: 1,
            },
          ],
          total: 1,
          next_cursor: null,
          truncated: false,
        }),
      ),
    })
    render(<IngestionPanel api={api} refreshToken={0} />)

    expect(await screen.findByTitle(filename)).toHaveTextContent(filename)
    expect(screen.getByText("settings_chunking_strategy_sentence_window")).toBeVisible()
    const moduleName = ["node", "fs"].join(":")
    const fileSystem = (await import(moduleName)) as unknown as FileSystemModule
    const styles = fileSystem.readFileSync("src/features/ingestion/ingestion.css", "utf8")
    expect(styles).toMatch(/\.rs-document h3\s*\{[^}]*overflow-wrap:\s*anywhere/u)
    expect(styles).toMatch(/\.rs-document__summary[^}]*\{[^}]*flex-wrap:\s*wrap/u)
  })

  it("returns focus to Browse files when Escape dismisses a duplicate dialog", async () => {
    const upload = vi
      .fn<IngestionApi["upload"]>()
      .mockResolvedValueOnce({
        kind: "duplicate",
        response: {
          status: "duplicate",
          filename: "report.txt",
          existing_chunks: 4,
          existing_size: 128,
          stored_chunk_size: 512,
          stored_chunk_overlap: 64,
          new_file_size: 256,
          estimated_chunks: 2,
          chunks_settings_changed: false,
          current_chunk_size: 512,
          current_chunk_overlap: 64,
        },
      })
      .mockResolvedValueOnce({
        kind: "accepted",
        response: { status: "cancelled", file_id: "", message: "cancelled" },
      })
    render(<IngestionPanel api={emptyApi({ upload })} refreshToken={0} />)
    const browse = screen.getByLabelText("settings_browse_files")
    const file = new File(["replacement"], "report.txt", { type: "text/plain" })
    browse.focus()
    fireEvent.change(screen.getByLabelText("settings_browse_files"), {
      target: { files: [file] },
    })
    await screen.findByRole("dialog", { name: "duplicate_modal_title" })

    await userEvent.keyboard("{Escape}")

    await waitFor(() => expect(browse).toHaveFocus())
    expect(screen.queryByRole("dialog", { name: "duplicate_modal_title" })).not.toBeInTheDocument()
  })

  it.each(["cancel", "rename", "replace"] as const)(
    "offers all duplicate decisions and sends the %s action with the same file",
    async (action) => {
      const upload = vi
        .fn()
        .mockResolvedValueOnce({
          kind: "duplicate",
          response: {
            status: "duplicate",
            filename: "report.txt",
            existing_chunks: 4,
            existing_size: 128,
            stored_chunk_size: 512,
            stored_chunk_overlap: 64,
            new_file_size: 256,
            estimated_chunks: 2,
            chunks_settings_changed: true,
            current_chunk_size: 1024,
            current_chunk_overlap: 128,
          },
        })
        .mockResolvedValueOnce({
          kind: "accepted",
          response: {
            status: action === "cancel" ? "cancelled" : "unchanged",
            file_id: "",
            message: action,
          },
        })
      const api = emptyApi({ upload })
      render(<IngestionPanel api={api} refreshToken={0} />)
      const file = new File(["replacement"], "report.txt", { type: "text/plain" })

      fireEvent.change(screen.getByLabelText("settings_browse_files"), {
        target: { files: [file] },
      })

      expect(await screen.findByRole("dialog", { name: "duplicate_modal_title" })).toBeVisible()
      expect(screen.getByRole("button", { name: "duplicate_replace" })).toBeVisible()
      expect(screen.getByRole("button", { name: "duplicate_rename" })).toBeVisible()
      await userEvent.click(screen.getByRole("button", { name: `duplicate_${action}` }))

      await waitFor(() => {
        expect(upload).toHaveBeenNthCalledWith(2, file, action, expect.any(AbortSignal))
      })
    },
  )

  it("loads document chunks only after expansion and preserves CSV strategy metadata", async () => {
    const chunks = vi.fn(() =>
      Promise.resolve({
        chunks: [
          { point_id: "p-1", chunk_index: 0, text: "row content", token_count: 2, page: null },
        ],
        next_cursor: null,
        truncated: false,
      }),
    )
    const api = emptyApi({
      chunks,
      documents: vi.fn(() =>
        Promise.resolve({
          documents: [
            {
              doc_id: "doc-1",
              filename: "records.csv",
              chunks_count: 1,
              chunk_size: 0,
              chunk_overlap: 0,
              created_at: "2026-08-15T00:00:00Z",
              strategy: "csv_row",
              schema_version: 1,
            },
          ],
          total: 1,
          next_cursor: null,
          truncated: false,
        }),
      ),
    })
    render(<IngestionPanel api={api} refreshToken={0} />)

    expect(await screen.findByText("csv_row")).toBeVisible()
    expect(chunks).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole("button", { name: "settings_doc_col_chunks" }))

    expect(await screen.findByText("row content")).toBeVisible()
    expect(chunks).toHaveBeenCalledWith("doc-1", undefined, expect.any(AbortSignal))
  })

  it("pauses a multi-file batch at its first duplicate and resumes after the decision", async () => {
    const duplicate = {
      status: "duplicate" as const,
      filename: "first.txt",
      existing_chunks: 1,
      existing_size: 10,
      stored_chunk_size: 512,
      stored_chunk_overlap: 64,
      new_file_size: 12,
      estimated_chunks: 1,
      chunks_settings_changed: false,
      current_chunk_size: 512,
      current_chunk_overlap: 64,
    }
    const upload = vi
      .fn<IngestionApi["upload"]>()
      .mockResolvedValueOnce({ kind: "duplicate", response: duplicate })
      .mockResolvedValueOnce({
        kind: "accepted",
        response: { status: "cancelled", file_id: "", message: "cancelled" },
      })
      .mockResolvedValueOnce({
        kind: "accepted",
        response: { status: "unchanged", file_id: "", message: "second indexed" },
      })
    render(<IngestionPanel api={emptyApi({ upload })} refreshToken={0} />)
    const first = new File(["first"], "first.txt", { type: "text/plain" })
    const second = new File(["second"], "second.txt", { type: "text/plain" })

    fireEvent.change(screen.getByLabelText("settings_browse_files"), {
      target: { files: [first, second] },
    })
    expect(await screen.findByRole("dialog", { name: "duplicate_modal_title" })).toBeVisible()
    expect(upload).toHaveBeenCalledTimes(1)

    await userEvent.click(screen.getByRole("button", { name: "duplicate_cancel" }))

    await waitFor(() => expect(upload).toHaveBeenCalledTimes(3))
    expect(upload).toHaveBeenNthCalledWith(2, first, "cancel", expect.any(AbortSignal))
    expect(upload).toHaveBeenNthCalledWith(3, second, "default", expect.any(AbortSignal))
    expect(screen.getAllByText("ingestion_status_cancelled")).toHaveLength(2)
    expect(screen.getAllByText("ingestion_status_unchanged")).toHaveLength(2)
    expect(screen.queryByText("cancelled")).not.toBeInTheDocument()
    expect(screen.queryByText("second indexed")).not.toBeInTheDocument()
  })
})

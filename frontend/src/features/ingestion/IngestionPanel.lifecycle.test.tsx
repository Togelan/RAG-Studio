import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import ruMessages from "../../../../src/api/locales/ru.json"
import { ApiError } from "../../api/errors"
import type { TranslationKey } from "../../i18n/locale-inventory"
import { IngestionPanel } from "./IngestionPanel"
import type { IngestionApi } from "./ingestion-api"
import type { DocumentRecord, DocumentsPage } from "./ingestion-schemas"

const localeMock = vi.hoisted(() => ({
  locale: "en" as "en" | "ru",
  messages: {} as Readonly<Record<string, string>>,
}))

vi.mock("../../app/locale-provider", () => ({
  useLocaleContext: () => ({
    locale: localeMock.locale,
    t: (key: TranslationKey) => localeMock.messages[key] ?? key,
    format: (key: TranslationKey, values: { readonly count?: number; readonly name?: string }) =>
      `${key}:${values.count ?? values.name}`,
  }),
}))

afterEach(() => {
  cleanup()
  localeMock.locale = "en"
  localeMock.messages = {}
})

const document: DocumentRecord = {
  doc_id: "doc-1",
  filename: "ready.txt",
  chunks_count: 2,
  chunk_size: 512,
  chunk_overlap: 64,
  created_at: "2026-08-15T00:00:00Z",
  strategy: "recursive",
  schema_version: 1,
}

function page(
  documents: readonly DocumentRecord[],
  nextCursor: string | null = null,
): DocumentsPage {
  return {
    documents: [...documents],
    total: documents.length,
    next_cursor: nextCursor,
    truncated: nextCursor !== null,
  }
}

function api(overrides: Partial<IngestionApi> = {}): IngestionApi {
  return {
    chunks: vi.fn(() => Promise.resolve({ chunks: [], next_cursor: null, truncated: false })),
    clear: vi.fn(() =>
      Promise.resolve({ status: "ok" as const, message: "cleared", deleted_count: 1 }),
    ),
    deleteDocument: vi.fn(() =>
      Promise.resolve({ status: "ok" as const, message: "deleted", deleted_count: 1 }),
    ),
    documents: vi.fn(() => Promise.resolve(page([]))),
    progress: vi.fn(() =>
      Promise.resolve({
        file_id: "job-1",
        status: "done" as const,
        message: "indexed",
        chunks_count: 2,
      }),
    ),
    reingest: vi.fn(() =>
      Promise.resolve({ status: "processing" as const, file_id: "job-1", message: "queued" }),
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

describe("IngestionPanel lifecycle", () => {
  it("polls an accepted upload to ready and refreshes the document list", async () => {
    const documents = vi
      .fn()
      .mockResolvedValueOnce(page([]))
      .mockResolvedValueOnce(page([document]))
    const progress = vi.fn(() =>
      Promise.resolve({
        file_id: "job-1",
        status: "done" as const,
        message: "indexed",
        chunks_count: 2,
      }),
    )
    const upload = vi.fn(() =>
      Promise.resolve({
        kind: "accepted" as const,
        response: { status: "processing" as const, file_id: "job-1", message: "queued" },
      }),
    )
    render(<IngestionPanel api={api({ documents, progress, upload })} refreshToken={0} />)
    await screen.findByText("settings_no_documents")

    const file = new File(["safe"], "ready.txt", { type: "text/plain" })
    fireEvent.change(screen.getByLabelText("settings_browse_files"), { target: { files: [file] } })

    expect(await screen.findAllByText("status_ready", {}, { timeout: 2500 })).toHaveLength(2)
    expect(await screen.findByRole("heading", { name: "ready.txt" })).toBeVisible()
    expect(progress).toHaveBeenCalledWith("job-1", expect.any(AbortSignal))
    expect(documents).toHaveBeenCalledTimes(2)
  })

  it("renders real upload and polling payloads through the authoritative Russian map", async () => {
    localeMock.locale = "ru"
    localeMock.messages = ruMessages
    const progress = vi.fn(() =>
      Promise.resolve({
        file_id: "job-ru",
        status: "processing" as const,
        message: "Waiting for the next progress update…",
      }),
    )
    const upload = vi.fn(() =>
      Promise.resolve({
        kind: "accepted" as const,
        response: { status: "processing" as const, file_id: "job-ru", message: "Uploading…" },
      }),
    )
    render(<IngestionPanel api={api({ progress, upload })} refreshToken={0} />)
    await screen.findByText(ruMessages.settings_no_documents)

    fireEvent.change(screen.getByLabelText(ruMessages.settings_browse_files), {
      target: { files: [new File(["safe"], "ru.txt", { type: "text/plain" })] },
    })

    expect(await screen.findByText(ruMessages.ingestion_uploading)).toBeVisible()
    expect(
      await screen.findByText(ruMessages.ingestion_waiting_progress, {}, { timeout: 2500 }),
    ).toBeVisible()
    expect(screen.queryByText("Uploading…")).not.toBeInTheDocument()
    expect(screen.queryByText("Waiting for the next progress update…")).not.toBeInTheDocument()
  })

  it("ignores a stale document refresh after the API gateway changes", async () => {
    let resolveStale: ((value: DocumentsPage) => void) | undefined
    const stale = new Promise<DocumentsPage>((resolve) => {
      resolveStale = resolve
    })
    const oldApi = api({ documents: vi.fn(() => stale) })
    const currentDocument = { ...document, doc_id: "current", filename: "current.txt" }
    const currentApi = api({ documents: vi.fn(() => Promise.resolve(page([currentDocument]))) })
    const view = render(<IngestionPanel api={oldApi} refreshToken={0} />)

    view.rerender(<IngestionPanel api={currentApi} refreshToken={0} />)
    expect(await screen.findByRole("heading", { name: "current.txt" })).toBeVisible()
    resolveStale?.(page([{ ...document, doc_id: "stale", filename: "stale.txt" }]))
    await Promise.resolve()

    expect(screen.queryByText("stale.txt")).not.toBeInTheDocument()
    expect(screen.getByText("current.txt")).toBeVisible()
  })

  it("preserves the old page and sanitizes a failed cursor continuation", async () => {
    const hostile = "C:\\secret\\provider-key"
    const documents = vi
      .fn()
      .mockResolvedValueOnce(page([document], "cursor/next"))
      .mockRejectedValueOnce(new Error(hostile))
    render(<IngestionPanel api={api({ documents })} refreshToken={0} />)
    await screen.findByText("ready.txt")

    await userEvent.click(screen.getByRole("button", { name: "ingestion_load_more_documents" }))

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The document request could not be completed. Please try again.",
    )
    expect(screen.getByText("ready.txt")).toBeVisible()
    expect(screen.queryByText(hostile)).not.toBeInTheDocument()
  })

  it.each([400, 422, 429, 503])("shows a sanitized initial documents status %s", async (status) => {
    const hostile = "provider body /private/path secret"
    render(
      <IngestionPanel
        api={api({
          documents: vi.fn(() =>
            Promise.reject(
              new ApiError(
                status,
                status >= 500 ? "Service unavailable" : "Request rejected",
                null,
              ),
            ),
          ),
        })}
        refreshToken={0}
      />,
    )

    const alert = await screen.findByRole("alert")
    expect(alert).not.toHaveTextContent(hostile)
    expect(alert).toHaveTextContent(status >= 500 ? "Service unavailable" : "Request rejected")
  })
})

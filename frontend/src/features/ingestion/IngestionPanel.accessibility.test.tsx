import { cleanup, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

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

function emptyApi(): IngestionApi {
  return {
    chunks: vi.fn(() => Promise.resolve({ chunks: [], next_cursor: null, truncated: false })),
    clear: vi.fn<IngestionApi["clear"]>(() =>
      Promise.resolve({ status: "ok", message: "", deleted_count: 0 }),
    ),
    deleteDocument: vi.fn<IngestionApi["deleteDocument"]>(() =>
      Promise.resolve({ status: "ok", message: "", deleted_count: 0 }),
    ),
    documents: vi.fn(() =>
      Promise.resolve({ documents: [], total: 0, next_cursor: null, truncated: false }),
    ),
    progress: vi.fn<IngestionApi["progress"]>(() =>
      Promise.resolve({ file_id: "job", status: "done", message: "", chunks_count: 1 }),
    ),
    reingest: vi.fn<IngestionApi["reingest"]>(() =>
      Promise.resolve({ status: "processing", file_id: "job", message: "" }),
    ),
    upload: vi.fn<IngestionApi["upload"]>(() =>
      Promise.resolve({
        kind: "accepted",
        response: { status: "unchanged", file_id: "", message: "" },
      }),
    ),
  }
}

describe("IngestionPanel accessibility", () => {
  it("associates supported formats and the batch limit with the native file picker", () => {
    render(<IngestionPanel api={emptyApi()} refreshToken={0} />)

    const picker = screen.getByLabelText("settings_browse_files")
    const guidance = screen.getByText("settings_upload_file_types_helper:20")

    expect(guidance).toHaveAttribute("id", "personal-knowledge-file-guidance")
    expect(picker).toHaveAttribute("aria-describedby", guidance.id)
    expect(picker).toHaveAttribute("accept", ".txt,.md,.pdf,.docx,.csv")
    expect(picker).toHaveAttribute("multiple")
  })
})

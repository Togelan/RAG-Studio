import { describe, expect, it, vi } from "vitest"

import type { IngestionApi } from "./ingestion-api"
import { loadAllDocuments, runReingestBatch } from "./ingestion-batch"
import type { DocumentRecord } from "./ingestion-schemas"

const documentA: DocumentRecord = {
  doc_id: "doc-a",
  filename: "a.txt",
  chunks_count: 1,
  chunk_size: 512,
  chunk_overlap: 64,
  created_at: "2026-08-15T00:00:00Z",
  strategy: "recursive",
  schema_version: 1,
}

describe("ingestion batch orchestration", () => {
  it("loads every bounded document page using each returned cursor", async () => {
    const documents = vi
      .fn()
      .mockResolvedValueOnce({
        documents: [documentA],
        total: null,
        next_cursor: "page-2",
        truncated: true,
      })
      .mockResolvedValueOnce({
        documents: [{ ...documentA, doc_id: "doc-b", filename: "b.txt" }],
        total: 2,
        next_cursor: null,
        truncated: false,
      })

    const result = await loadAllDocuments({ documents } as Pick<IngestionApi, "documents">)

    expect(result.map((document) => document.doc_id)).toEqual(["doc-a", "doc-b"])
    expect(documents).toHaveBeenNthCalledWith(2, "page-2", undefined)
  })

  it("loads one thousand documents across bounded pages", async () => {
    // Given
    const expected = Array.from({ length: 1_000 }, (_, index) => ({
      ...documentA,
      doc_id: `doc-${index}`,
      filename: `document-${index}.txt`,
    }))
    const documents = vi.fn((cursor?: string) => {
      const offset = Number(cursor ?? "0")
      const page = expected.slice(offset, offset + 100)
      const nextOffset = offset + page.length
      return Promise.resolve({
        documents: page,
        total: expected.length,
        next_cursor: nextOffset < expected.length ? String(nextOffset) : null,
        truncated: nextOffset < expected.length,
      })
    })

    // When
    const result = await loadAllDocuments({ documents })

    // Then
    expect(result).toHaveLength(1_000)
    expect(result[0]?.doc_id).toBe("doc-0")
    expect(result[999]?.doc_id).toBe("doc-999")
    expect(documents).toHaveBeenCalledTimes(10)
  })

  it("continues after skipped and failed documents while waiting for terminal success", async () => {
    const reingest = vi
      .fn()
      .mockResolvedValueOnce({ status: "processing", file_id: "job-a", message: "queued" })
      .mockResolvedValueOnce({ status: "skipped", file_id: "doc-b", message: "missing" })
      .mockRejectedValueOnce(new Error("failed"))
    const progress = vi.fn()
    const waitForTerminal = vi.fn(() => Promise.resolve("done" as const))
    const documents = [
      documentA,
      { ...documentA, doc_id: "doc-b", filename: "b.txt" },
      { ...documentA, doc_id: "doc-c", filename: "c.txt" },
    ]

    const result = await runReingestBatch(documents, {
      api: {
        progress: vi.fn(() =>
          Promise.resolve({ file_id: "job", status: "done" as const, message: "done" }),
        ),
        reingest,
      },
      onProgress: progress,
      waitForTerminal,
    })

    expect(waitForTerminal).toHaveBeenCalledWith("job-a", expect.any(AbortSignal))
    expect(result).toEqual({ failed: 1, skipped: 1, succeeded: 1, total: 3 })
    expect(progress).toHaveBeenCalledTimes(3)
  })
})

import type { IngestionApi, ReingestSummary } from "./ingestion-api"
import type { DocumentRecord } from "./ingestion-schemas"

const MAX_DOCUMENT_PAGES = 100
const MAX_PROGRESS_POLLS = 400
const PROGRESS_POLL_MS = 750

export class PaginationLimitError extends Error {
  readonly name = "PaginationLimitError"

  constructor() {
    super("The document list exceeded the bounded pagination limit.")
  }
}

export class ProgressTimeoutError extends Error {
  readonly name = "ProgressTimeoutError"

  constructor() {
    super("Re-ingestion did not reach a terminal state in time.")
  }
}

export type TerminalProgress = "done" | "error"
export type WaitForTerminal = (fileId: string, signal: AbortSignal) => Promise<TerminalProgress>

type ReingestBatchOptions = {
  readonly api: Pick<IngestionApi, "progress" | "reingest">
  readonly onProgress: (completed: number, total: number) => void
  readonly signal?: AbortSignal
  readonly waitForTerminal?: WaitForTerminal
}

function abortSignal(signal: AbortSignal | undefined): AbortSignal {
  return signal ?? new AbortController().signal
}

function delay(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const onAbort = (): void => {
      window.clearTimeout(timer)
      reject(new DOMException("Aborted", "AbortError"))
    }
    const timer = window.setTimeout(() => {
      signal.removeEventListener("abort", onAbort)
      resolve()
    }, milliseconds)
    signal.addEventListener("abort", onAbort, { once: true })
  })
}

export async function loadAllDocuments(
  api: Pick<IngestionApi, "documents">,
  signal?: AbortSignal,
): Promise<readonly DocumentRecord[]> {
  const result: DocumentRecord[] = []
  const seenCursors = new Set<string>()
  let cursor: string | undefined

  for (let pageNumber = 0; pageNumber < MAX_DOCUMENT_PAGES; pageNumber += 1) {
    const page = await api.documents(cursor, signal)
    result.push(...page.documents)
    if (page.next_cursor === null) return result
    if (seenCursors.has(page.next_cursor)) throw new PaginationLimitError()
    seenCursors.add(page.next_cursor)
    cursor = page.next_cursor
  }
  throw new PaginationLimitError()
}

export async function waitForTerminalProgress(
  api: Pick<IngestionApi, "progress">,
  fileId: string,
  signal: AbortSignal,
): Promise<TerminalProgress> {
  for (let attempt = 0; attempt < MAX_PROGRESS_POLLS; attempt += 1) {
    await delay(PROGRESS_POLL_MS, signal)
    const progress = await api.progress(fileId, signal)
    if (progress.status !== "processing") return progress.status
  }
  throw new ProgressTimeoutError()
}

export async function runReingestBatch(
  documents: readonly Pick<DocumentRecord, "doc_id" | "filename">[],
  options: ReingestBatchOptions,
): Promise<ReingestSummary> {
  const signal = abortSignal(options.signal)
  const wait =
    options.waitForTerminal ??
    ((fileId, activeSignal) => waitForTerminalProgress(options.api, fileId, activeSignal))
  let succeeded = 0
  let skipped = 0
  let failed = 0

  for (const document of documents) {
    try {
      const response = await options.api.reingest(document, signal)
      if (response.status === "skipped") {
        skipped += 1
      } else {
        const terminal = await wait(response.file_id, signal)
        if (terminal === "done") succeeded += 1
        else failed += 1
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") throw error
      if (!(error instanceof Error)) throw error
      failed += 1
    }
    options.onProgress(succeeded + skipped + failed, documents.length)
  }

  return { failed, skipped, succeeded, total: documents.length }
}

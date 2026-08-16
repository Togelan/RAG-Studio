import { ApiContractError, ApiError } from "../../api/errors"

export const MAX_PROGRESS_POLLS = 400
export const POLL_INTERVAL_MS = 750

export function safeIngestionMessage(error: unknown): string {
  if (error instanceof ApiError || error instanceof ApiContractError) return error.message
  return "The document request could not be completed. Please try again."
}

export function delayWithAbort(milliseconds: number, signal: AbortSignal): Promise<void> {
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

export function uploadId(file: File): string {
  return `${file.name}-${file.size}-${file.lastModified}`
}

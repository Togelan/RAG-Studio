import { useCallback, useEffect, useRef, useState } from "react"

import { ApiContractError, ApiError, isAbortError } from "../../api/errors"
import type { IngestionApi, UploadAction } from "./ingestion-api"
import {
  delayWithAbort,
  MAX_PROGRESS_POLLS,
  POLL_INTERVAL_MS,
  safeIngestionMessage,
  uploadId,
} from "./ingestion-runtime"
import type { DocumentRecord, DuplicateResponse } from "./ingestion-schemas"

export type UploadItem = {
  readonly id: string
  readonly messageKey:
    | "ingestion_progress_unavailable"
    | "ingestion_status_cancelled"
    | "ingestion_status_unchanged"
    | "ingestion_upload_failed"
    | "ingestion_uploading"
    | "ingestion_waiting_progress"
    | "status_ready"
  readonly name: string
  readonly status: "cancelled" | "error" | "processing" | "ready" | "unchanged"
}

type UploadOutcome = "complete" | "duplicate"

export type DuplicateDecision = {
  readonly file: File
  readonly response: DuplicateResponse
}

export type IngestionController = {
  readonly clearDocuments: () => Promise<void>
  readonly deleteDocument: (docId: string) => Promise<void>
  readonly documents: readonly DocumentRecord[]
  readonly duplicate: DuplicateDecision | null
  readonly error: string | null
  readonly hasMore: boolean
  readonly isLoading: boolean
  readonly loadMore: () => Promise<void>
  readonly refresh: () => Promise<void>
  readonly resolveDuplicate: (action: Exclude<UploadAction, "default">) => Promise<void>
  readonly uploads: readonly UploadItem[]
  readonly uploadFiles: (files: readonly File[]) => Promise<void>
}

export function useIngestionController(
  api: IngestionApi,
  refreshToken: number,
): IngestionController {
  const [documents, setDocuments] = useState<readonly DocumentRecord[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [uploads, setUploads] = useState<readonly UploadItem[]>([])
  const [duplicate, setDuplicate] = useState<DuplicateDecision | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const controllers = useRef(new Set<AbortController>())
  const refreshRequest = useRef(0)
  const pendingFiles = useRef<readonly File[]>([])

  const trackedController = useCallback((): AbortController => {
    const controller = new AbortController()
    controllers.current.add(controller)
    return controller
  }, [])

  const release = useCallback((controller: AbortController): void => {
    controllers.current.delete(controller)
  }, [])

  const refresh = useCallback(async (): Promise<void> => {
    const requestId = refreshRequest.current + 1
    refreshRequest.current = requestId
    const controller = trackedController()
    setIsLoading(true)
    setError(null)
    try {
      const page = await api.documents(undefined, controller.signal)
      if (requestId !== refreshRequest.current) return
      setDocuments(page.documents)
      setNextCursor(page.next_cursor)
    } catch (caught) {
      if (!isAbortError(caught) && requestId === refreshRequest.current) {
        setError(safeIngestionMessage(caught))
      }
    } finally {
      release(controller)
      if (requestId === refreshRequest.current) setIsLoading(false)
    }
  }, [api, release, trackedController])

  useEffect(() => {
    void refreshToken
    void refresh()
  }, [refresh, refreshToken])

  useEffect(
    () => () => {
      for (const controller of controllers.current) {
        controller.abort()
      }
      controllers.current.clear()
    },
    [],
  )

  const updateUpload = useCallback((item: UploadItem): void => {
    setUploads((current) => [...current.filter((entry) => entry.id !== item.id), item])
  }, [])

  const poll = useCallback(
    async (file: File, fileId: string, controller: AbortController): Promise<void> => {
      for (let attempt = 0; attempt < MAX_PROGRESS_POLLS; attempt += 1) {
        await delayWithAbort(POLL_INTERVAL_MS, controller.signal)
        let progress: Awaited<ReturnType<IngestionApi["progress"]>>
        try {
          progress = await api.progress(fileId, controller.signal)
        } catch (caught) {
          if (isAbortError(caught)) throw caught
          if (caught instanceof ApiError || caught instanceof ApiContractError) throw caught
          updateUpload({
            id: uploadId(file),
            messageKey: "ingestion_progress_unavailable",
            name: file.name,
            status: "processing",
          })
          continue
        }
        if (progress.status === "processing") {
          updateUpload({
            id: uploadId(file),
            messageKey: "ingestion_waiting_progress",
            name: file.name,
            status: "processing",
          })
          continue
        }
        updateUpload({
          id: uploadId(file),
          messageKey: progress.status === "done" ? "status_ready" : "ingestion_upload_failed",
          name: file.name,
          status: progress.status === "done" ? "ready" : "error",
        })
        if (progress.status === "done") {
          await refresh()
        }
        return
      }
      updateUpload({
        id: uploadId(file),
        messageKey: "ingestion_progress_unavailable",
        name: file.name,
        status: "error",
      })
    },
    [api, refresh, updateUpload],
  )

  const performUpload = useCallback(
    async (file: File, action: UploadAction): Promise<UploadOutcome> => {
      const controller = trackedController()
      updateUpload({
        id: uploadId(file),
        messageKey: "ingestion_uploading",
        name: file.name,
        status: "processing",
      })
      try {
        const result = await api.upload(file, action, controller.signal)
        if (result.kind === "duplicate") {
          setDuplicate({ file, response: result.response })
          return "duplicate"
        }
        const response = result.response
        if (response.status === "processing") {
          await poll(file, response.file_id, controller)
          return "complete"
        }
        updateUpload({
          id: uploadId(file),
          messageKey:
            response.status === "cancelled"
              ? "ingestion_status_cancelled"
              : "ingestion_status_unchanged",
          name: file.name,
          status:
            response.status === "cancelled"
              ? "cancelled"
              : response.status === "unchanged"
                ? "unchanged"
                : "ready",
        })
      } catch (caught) {
        if (!isAbortError(caught)) {
          updateUpload({
            id: uploadId(file),
            messageKey: "ingestion_progress_unavailable",
            name: file.name,
            status: "error",
          })
        }
      } finally {
        release(controller)
      }
      return "complete"
    },
    [api, poll, release, trackedController, updateUpload],
  )

  const continueUploads = useCallback(
    async (files: readonly File[]): Promise<void> => {
      for (let index = 0; index < files.length; index += 1) {
        const file = files[index]
        if (file === undefined) continue
        const outcome = await performUpload(file, "default")
        if (outcome === "duplicate") {
          pendingFiles.current = files.slice(index + 1)
          return
        }
      }
      pendingFiles.current = []
    },
    [performUpload],
  )

  return {
    documents,
    duplicate,
    error,
    hasMore: nextCursor !== null,
    isLoading,
    uploads,
    refresh,
    loadMore: async (): Promise<void> => {
      if (nextCursor === null) return
      const controller = trackedController()
      try {
        const page = await api.documents(nextCursor, controller.signal)
        setDocuments((current) => [...current, ...page.documents])
        setNextCursor(page.next_cursor)
      } catch (caught) {
        if (!isAbortError(caught)) setError(safeIngestionMessage(caught))
      } finally {
        release(controller)
      }
    },
    uploadFiles: async (files): Promise<void> => {
      pendingFiles.current = []
      await continueUploads(files)
    },
    resolveDuplicate: async (action): Promise<void> => {
      const decision = duplicate
      setDuplicate(null)
      if (decision === null) return
      const outcome = await performUpload(decision.file, action)
      if (outcome === "duplicate") return
      const remaining = pendingFiles.current
      pendingFiles.current = []
      await continueUploads(remaining)
    },
    deleteDocument: async (docId): Promise<void> => {
      const controller = trackedController()
      try {
        await api.deleteDocument(docId, controller.signal)
        await refresh()
      } catch (caught) {
        if (!isAbortError(caught)) setError(safeIngestionMessage(caught))
      } finally {
        release(controller)
      }
    },
    clearDocuments: async (): Promise<void> => {
      const controller = trackedController()
      try {
        await api.clear(controller.signal)
        setDocuments([])
        setNextCursor(null)
      } catch (caught) {
        if (!isAbortError(caught)) setError(safeIngestionMessage(caught))
      } finally {
        release(controller)
      }
    },
  }
}

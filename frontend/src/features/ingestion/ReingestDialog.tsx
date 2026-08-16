import { type RefObject, useEffect, useRef, useState } from "react"

import { useLocaleContext } from "../../app/locale-provider"
import { Button } from "../../components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "../../components/ui/dialog"
import { Progress } from "../../components/ui/progress"
import type { IngestionApi, ReingestSummary } from "./ingestion-api"
import { loadAllDocuments, runReingestBatch } from "./ingestion-batch"

type ReingestDialogProps = {
  readonly api: IngestionApi
  readonly onBeforeReingest: () => Promise<boolean>
  readonly onClose: () => void
  readonly onComplete: (summary: ReingestSummary) => void
  readonly onSkip: () => Promise<boolean>
  readonly open: boolean
  readonly restoreFocusRef: RefObject<HTMLElement | null>
}

export function ReingestDialog({
  api,
  onBeforeReingest,
  onClose,
  onComplete,
  onSkip,
  open,
  restoreFocusRef,
}: ReingestDialogProps): React.JSX.Element {
  const { t } = useLocaleContext()
  const controllerRef = useRef<AbortController | null>(null)
  const [completed, setCompleted] = useState(0)
  const [total, setTotal] = useState(0)
  const [running, setRunning] = useState(false)
  const [summary, setSummary] = useState<ReingestSummary | null>(null)
  const [error, setError] = useState(false)

  useEffect(
    () => () => {
      controllerRef.current?.abort()
    },
    [],
  )

  const close = (): void => {
    controllerRef.current?.abort()
    setRunning(false)
    setSummary(null)
    setError(false)
    onClose()
  }

  const begin = async (): Promise<void> => {
    const controller = new AbortController()
    controllerRef.current = controller
    setRunning(true)
    setError(false)
    setCompleted(0)
    try {
      if (!(await onBeforeReingest())) {
        setError(true)
        return
      }
      const documents = await loadAllDocuments(api, controller.signal)
      setTotal(documents.length)
      const result = await runReingestBatch(documents, {
        api,
        onProgress: (current, count) => {
          setCompleted(current)
          setTotal(count)
        },
        signal: controller.signal,
      })
      setSummary(result)
      onComplete(result)
    } catch (caught) {
      if (!(caught instanceof DOMException && caught.name === "AbortError")) setError(true)
    } finally {
      setRunning(false)
    }
  }

  const skip = async (): Promise<void> => {
    setRunning(true)
    setError(false)
    try {
      if (await onSkip()) close()
      else setError(true)
    } finally {
      setRunning(false)
    }
  }

  return (
    <Dialog
      onOpenChange={(nextOpen) => {
        if (!nextOpen) close()
      }}
      open={open}
    >
      <DialogContent
        aria-describedby="reingest-description"
        onCloseAutoFocus={(event) => {
          event.preventDefault()
          restoreFocusRef.current?.focus()
        }}
      >
        <DialogTitle>{t("reingest_modal_title")}</DialogTitle>
        <DialogDescription id="reingest-description">
          {t("reingest_modal_message")}
        </DialogDescription>
        {running || summary !== null ? (
          <div className="rs-reingest-progress" role="status">
            <Progress label={t("reingest_progress")} max={Math.max(total, 1)} value={completed} />
            <p>
              {running
                ? `${t("reingest_progress")} ${completed} / ${total}`
                : summary?.failed
                  ? t("reingest_complete_errors")
                  : t("reingest_complete")}
            </p>
            {summary ? (
              <small>
                {t("ingestion_succeeded")}: {summary.succeeded} · {t("ingestion_skipped")}:{" "}
                {summary.skipped} · {t("ingestion_failed")}: {summary.failed}
              </small>
            ) : null}
          </div>
        ) : null}
        {error ? (
          <p className="rs-notice rs-notice--danger" role="alert">
            {t("reingest_error")}
          </p>
        ) : null}
        <div className="rs-dialog-actions">
          <Button
            disabled={running}
            onClick={summary === null ? () => void skip() : close}
            variant="secondary"
          >
            {summary === null ? t("reingest_skip") : t("confirm_ok")}
          </Button>
          {summary === null ? (
            <Button disabled={running} onClick={() => void begin()} variant="danger">
              {t("reingest_confirm")}
            </Button>
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  )
}

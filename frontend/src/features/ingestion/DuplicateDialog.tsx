import type { RefObject } from "react"

import { useLocaleContext } from "../../app/locale-provider"
import { Button } from "../../components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "../../components/ui/dialog"
import type { UploadAction } from "./ingestion-api"
import type { DuplicateDecision } from "./use-ingestion"

type DuplicateDialogProps = {
  readonly decision: DuplicateDecision | null
  readonly onDecision: (action: Exclude<UploadAction, "default">) => void
  readonly restoreFocusRef: RefObject<HTMLElement | null>
}

export function DuplicateDialog({
  decision,
  onDecision,
  restoreFocusRef,
}: DuplicateDialogProps): React.JSX.Element {
  const { t } = useLocaleContext()
  const duplicate = decision?.response
  const formatBytes = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} ${t("ingestion_unit_bytes")}`
    if (bytes < 1024 * 1024) {
      return `${(bytes / 1024).toFixed(1)} ${t("ingestion_unit_kilobytes")}`
    }
    return `${(bytes / (1024 * 1024)).toFixed(1)} ${t("ingestion_unit_megabytes")}`
  }

  return (
    <Dialog
      onOpenChange={(nextOpen) => {
        if (!nextOpen && decision !== null) onDecision("cancel")
      }}
      open={decision !== null}
    >
      <DialogContent
        aria-describedby="duplicate-description"
        onCloseAutoFocus={(event) => {
          event.preventDefault()
          restoreFocusRef.current?.focus()
        }}
      >
        <DialogTitle>{t("duplicate_modal_title")}</DialogTitle>
        <DialogDescription id="duplicate-description">
          <strong>{duplicate?.filename}</strong>
        </DialogDescription>
        {duplicate ? (
          <div className="rs-duplicate-grid">
            <section>
              <h3>{t("duplicate_existing_label")}</h3>
              <p>
                {t("duplicate_modal_chunks")}: {duplicate.existing_chunks}
              </p>
              <p>
                {t("duplicate_modal_size")}: {formatBytes(duplicate.existing_size)}
              </p>
              <p>
                {t("duplicate_chunk_settings")}: {duplicate.stored_chunk_size} /{" "}
                {duplicate.stored_chunk_overlap}
              </p>
            </section>
            <section>
              <h3>{t("duplicate_new_label")}</h3>
              <p>
                {t("duplicate_estimated_chunks")}: {duplicate.estimated_chunks}
              </p>
              <p>
                {t("duplicate_modal_size")}: {formatBytes(duplicate.new_file_size)}
              </p>
              <p>
                {t("duplicate_chunk_settings")}: {duplicate.current_chunk_size} /{" "}
                {duplicate.current_chunk_overlap}
              </p>
            </section>
          </div>
        ) : null}
        {duplicate?.chunks_settings_changed ? (
          <p className="rs-notice rs-notice--warning" role="status">
            {t("duplicate_modal_warning")}
          </p>
        ) : null}
        <div className="rs-dialog-actions">
          <Button onClick={() => onDecision("cancel")} variant="secondary">
            {t("duplicate_cancel")}
          </Button>
          <Button onClick={() => onDecision("rename")} variant="secondary">
            {t("duplicate_rename")}
          </Button>
          <Button onClick={() => onDecision("replace")} variant="danger">
            {t("duplicate_replace")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

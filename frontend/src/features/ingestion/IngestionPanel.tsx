import { FileUp, Trash2, UploadCloud } from "lucide-react"
import { useRef, useState } from "react"

import { useLocaleContext } from "../../app/locale-provider"
import { Button } from "../../components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "../../components/ui/dialog"
import { Progress } from "../../components/ui/progress"
import { DocumentRow } from "./DocumentRow"
import { DuplicateDialog } from "./DuplicateDialog"
import { type IngestionApi, ingestionApi } from "./ingestion-api"
import { useIngestionController } from "./use-ingestion"
import "./ingestion.css"

type IngestionPanelProps = {
  readonly api?: IngestionApi
  readonly refreshToken: number
}

const ACCEPTED_FILES = ".txt,.md,.pdf,.docx,.csv"
const MAX_BATCH_FILES = 20

export function IngestionPanel({
  api = ingestionApi,
  refreshToken,
}: IngestionPanelProps): React.JSX.Element {
  const { format, t } = useLocaleContext()
  const controller = useIngestionController(api, refreshToken)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const browseButtonRef = useRef<HTMLButtonElement | null>(null)
  const [dragActive, setDragActive] = useState(false)
  const [batchWarning, setBatchWarning] = useState<string | null>(null)
  const [clearOpen, setClearOpen] = useState(false)

  const acceptFiles = (list: FileList | null): void => {
    if (list === null) return
    const files = Array.from(list)
    if (files.length > MAX_BATCH_FILES) {
      setBatchWarning(format("ingestion_batch_limit", { count: MAX_BATCH_FILES }))
      return
    }
    setBatchWarning(null)
    void controller.uploadFiles(files)
  }

  return (
    <section aria-labelledby="documents-title" className="rs-ingestion">
      <div className="rs-ingestion__heading">
        <div>
          <p className="rs-settings-section__eyebrow">{t("settings_knowledge_index")}</p>
          <h2 id="documents-title">{t("settings_documents_title")}</h2>
        </div>
        {controller.documents.length > 0 ? (
          <Button
            className="rs-ingestion-clear-all"
            onClick={() => setClearOpen(true)}
            size="compact"
            variant="danger"
          >
            <Trash2 aria-hidden="true" size={16} />
            {t("ingestion_clear_all")}
          </Button>
        ) : null}
      </div>

      <fieldset
        className={`rs-dropzone${dragActive ? " rs-dropzone--active" : ""}`}
        onDragEnter={(event) => {
          event.preventDefault()
          setDragActive(true)
        }}
        onDragLeave={() => setDragActive(false)}
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => {
          event.preventDefault()
          setDragActive(false)
          acceptFiles(event.dataTransfer.files)
        }}
      >
        <legend className="rs-visually-hidden">{t("settings_drag_drop")}</legend>
        <UploadCloud aria-hidden="true" size={30} />
        <strong>{t("settings_drag_drop")}</strong>
        <span>{t("settings_or")}</span>
        <Button onClick={() => inputRef.current?.click()} ref={browseButtonRef} variant="secondary">
          <FileUp aria-hidden="true" size={17} />
          {t("settings_browse_files")}
        </Button>
        <input
          accept={ACCEPTED_FILES}
          aria-label={t("settings_browse_files")}
          className="rs-visually-hidden"
          multiple
          onChange={(event) => acceptFiles(event.currentTarget.files)}
          ref={inputRef}
          type="file"
        />
        <small>{format("settings_upload_file_types_helper", { count: MAX_BATCH_FILES })}</small>
      </fieldset>

      {batchWarning ? (
        <p className="rs-notice rs-notice--warning" role="alert">
          {batchWarning}
        </p>
      ) : null}
      {controller.error ? (
        <p className="rs-notice rs-notice--danger" role="alert">
          {controller.error}
        </p>
      ) : null}
      {controller.uploads.length > 0 ? (
        <div aria-label={t("ingestion_upload_progress")} className="rs-upload-list" role="status">
          {controller.uploads.map((upload) => (
            <div className="rs-upload" key={upload.id}>
              <div>
                <strong>{upload.name}</strong>
                <span>{t(upload.messageKey)}</span>
              </div>
              {upload.status === "processing" ? (
                <Progress
                  label={format("ingestion_upload_file_progress", { name: upload.name })}
                  value={null}
                />
              ) : (
                <span className={`rs-upload__status rs-upload__status--${upload.status}`}>
                  {upload.status === "ready" ? t("status_ready") : null}
                  {upload.status === "cancelled" ? t("ingestion_status_cancelled") : null}
                  {upload.status === "unchanged" ? t("ingestion_status_unchanged") : null}
                  {upload.status === "error" ? t("ingestion_status_failed") : null}
                </span>
              )}
            </div>
          ))}
        </div>
      ) : null}

      <div className="rs-document-list">
        {controller.isLoading ? <p role="status">{t("ingestion_loading_documents")}</p> : null}
        {!controller.isLoading && controller.documents.length === 0 ? (
          <div className="rs-empty-state">
            <FileUp aria-hidden="true" size={24} />
            <p>{t("settings_no_documents")}</p>
          </div>
        ) : null}
        {controller.documents.map((document) => (
          <DocumentRow
            api={api}
            document={document}
            key={document.doc_id}
            onDelete={controller.deleteDocument}
          />
        ))}
        {controller.hasMore ? (
          <Button onClick={() => void controller.loadMore()} variant="secondary">
            {t("ingestion_load_more_documents")}
          </Button>
        ) : null}
      </div>

      <DuplicateDialog
        decision={controller.duplicate}
        onDecision={(action) => void controller.resolveDuplicate(action)}
        restoreFocusRef={browseButtonRef}
      />
      <Dialog onOpenChange={setClearOpen} open={clearOpen}>
        <DialogContent>
          <DialogTitle>{t("ingestion_clear_all_title")}</DialogTitle>
          <DialogDescription>{t("ingestion_clear_all_message")}</DialogDescription>
          <div className="rs-dialog-actions">
            <Button onClick={() => setClearOpen(false)} variant="secondary">
              {t("settings_cancel")}
            </Button>
            <Button
              onClick={() => {
                setClearOpen(false)
                void controller.clearDocuments()
              }}
              variant="danger"
            >
              {t("ingestion_clear_all")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </section>
  )
}

import { ChevronDown, ChevronUp, FileText, Trash2 } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { useLocaleContext } from "../../app/locale-provider"
import { Badge } from "../../components/ui/badge"
import { Button } from "../../components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "../../components/ui/dialog"
import type { IngestionApi } from "./ingestion-api"
import type { ChunkRecord, DocumentRecord } from "./ingestion-schemas"

type DocumentRowProps = {
  readonly api: IngestionApi
  readonly document: DocumentRecord
  readonly onDelete: (docId: string) => Promise<void>
}

const strategyKeys = {
  static: "settings_chunking_strategy_static",
  recursive: "settings_chunking_strategy_recursive",
  parent_document: "settings_chunking_strategy_parent_document",
  sentence_window: "settings_chunking_strategy_sentence_window",
} as const

function strategyLabel(
  strategy: string,
  translate: ReturnType<typeof useLocaleContext>["t"],
): string {
  if (strategy in strategyKeys) {
    return translate(strategyKeys[strategy as keyof typeof strategyKeys])
  }
  return strategy
}

function extension(filename: string, unknownLabel: string): string {
  const dot = filename.lastIndexOf(".")
  return dot < 0 ? unknownLabel : filename.slice(dot + 1).toUpperCase()
}

function preview(text: string): string {
  return text.length <= 200 ? text : `${text.slice(0, 200)}…`
}

export function DocumentRow({ api, document, onDelete }: DocumentRowProps): React.JSX.Element {
  const { format, t } = useLocaleContext()
  const [expanded, setExpanded] = useState(false)
  const [chunks, setChunks] = useState<readonly ChunkRecord[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const controllerRef = useRef<AbortController | null>(null)

  useEffect(
    () => () => {
      controllerRef.current?.abort()
    },
    [],
  )

  const loadChunks = async (cursor?: string): Promise<void> => {
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller
    setLoading(true)
    setError(false)
    try {
      const page = await api.chunks(document.doc_id, cursor, controller.signal)
      setChunks((current) => (cursor === undefined ? page.chunks : [...current, ...page.chunks]))
      setNextCursor(page.next_cursor)
    } catch (caught) {
      if (!(caught instanceof DOMException && caught.name === "AbortError")) setError(true)
    } finally {
      setLoading(false)
    }
  }

  const toggle = (): void => {
    if (expanded) {
      setExpanded(false)
      return
    }
    setExpanded(true)
    if (chunks.length === 0) void loadChunks()
  }

  return (
    <article className="rs-document">
      <div className="rs-document__summary">
        <div className="rs-document__identity">
          <FileText aria-hidden="true" size={19} />
          <div>
            <h3 title={document.filename}>{document.filename}</h3>
            <p>
              {extension(document.filename, t("ingestion_file_type_unknown"))} ·{" "}
              {document.chunks_count} {t("settings_doc_col_chunks")} · {document.chunk_size} /{" "}
              {document.chunk_overlap} ·{" "}
              <time dateTime={document.created_at}>{document.created_at.slice(0, 10)}</time>
            </p>
          </div>
        </div>
        <div className="rs-document__actions">
          <Badge>{strategyLabel(document.strategy, t)}</Badge>
          <Button
            aria-expanded={expanded}
            className="rs-document-chunks-toggle"
            onClick={toggle}
            size="compact"
            variant="secondary"
          >
            {expanded ? (
              <ChevronUp aria-hidden="true" size={16} />
            ) : (
              <ChevronDown aria-hidden="true" size={16} />
            )}
            {expanded ? t("ingestion_hide_chunks") : t("settings_doc_col_chunks")}
          </Button>
          <Button
            aria-label={format("ingestion_delete_document_aria", { name: document.filename })}
            onClick={() => setConfirmOpen(true)}
            size="icon"
            variant="danger"
          >
            <Trash2 aria-hidden="true" size={17} />
          </Button>
        </div>
      </div>
      {expanded ? (
        <div className="rs-chunks">
          {loading && chunks.length === 0 ? (
            <p role="status">{t("ingestion_loading_chunks")}</p>
          ) : null}
          {error ? (
            <p className="rs-notice rs-notice--danger" role="alert">
              {t("ingestion_chunk_preview_unavailable")}
            </p>
          ) : null}
          {chunks.map((chunk) => (
            <section className="rs-chunk" key={chunk.point_id}>
              <div className="rs-chunk__meta">
                <strong>#{chunk.chunk_index + 1}</strong>
                <span>
                  {chunk.token_count} {t("ingestion_tokens")}
                  {chunk.page === null ? null : (
                    <>
                      {" · "}
                      {t("chat_page")} {chunk.page}
                    </>
                  )}
                </span>
              </div>
              <p>{preview(chunk.text)}</p>
            </section>
          ))}
          {nextCursor !== null ? (
            <Button
              disabled={loading}
              onClick={() => void loadChunks(nextCursor)}
              size="compact"
              variant="secondary"
            >
              {t("ingestion_load_more_chunks")}
            </Button>
          ) : null}
        </div>
      ) : null}
      <Dialog onOpenChange={setConfirmOpen} open={confirmOpen}>
        <DialogContent>
          <DialogTitle>{t("ingestion_delete_document_title")}</DialogTitle>
          <DialogDescription>
            {format("ingestion_delete_document_message", { name: document.filename })}
          </DialogDescription>
          <div className="rs-dialog-actions">
            <Button onClick={() => setConfirmOpen(false)} variant="secondary">
              {t("settings_cancel")}
            </Button>
            <Button
              onClick={() => {
                setConfirmOpen(false)
                void onDelete(document.doc_id)
              }}
              variant="danger"
            >
              {t("settings_delete")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </article>
  )
}

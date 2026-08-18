import { FileText, Trash2, Upload } from "lucide-react"
import { useEffect, useState } from "react"

import "./sources.css"

import { Button } from "../../../components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card"
import { Input } from "../../../components/ui/input"
import { Label } from "../../../components/ui/label"
import type { SaasLocale, WorkspaceRole } from "../model"
import { createSourcesGateway, type SourceDocument, type SourcesGateway } from "./sources-api"

type SourcesState =
  | { readonly kind: "loading" }
  | { readonly kind: "error" }
  | { readonly kind: "ready"; readonly documents: readonly SourceDocument[] }

type SourceCopy = {
  readonly confirm: string
  readonly confirmRemoval: string
  readonly description: string
  readonly empty: string
  readonly loadError: string
  readonly permission: string
  readonly remove: string
  readonly removeError: string
  readonly removeTitle: string
  readonly selected: string
  readonly sourceFile: string
  readonly title: string
  readonly upload: string
  readonly uploadError: string
  readonly uploading: string
}

const copy: Readonly<Record<SaasLocale, SourceCopy>> = {
  en: {
    confirm: "Confirm removal",
    confirmRemoval:
      "This removes the source from this workspace. It does not affect another workspace.",
    description: "Upload supported files to replace or extend this workspace's knowledge.",
    empty: "No sources have been added to this workspace yet.",
    loadError: "Sources could not be loaded. Please try again.",
    permission: "You do not have permission to manage sources.",
    remove: "Remove",
    removeError: "The source could not be removed. Please try again.",
    removeTitle: "Remove source?",
    selected: "Selected source",
    sourceFile: "Source file",
    title: "Sources",
    upload: "Upload source",
    uploadError: "The source could not be uploaded. Please try again.",
    uploading: "Uploading…",
  },
  ru: {
    confirm: "Подтвердить удаление",
    confirmRemoval: "Источник будет удалён только из этого пространства.",
    description: "Загрузите поддерживаемый файл, чтобы заменить или дополнить знания пространства.",
    empty: "В этом пространстве пока нет источников.",
    loadError: "Не удалось загрузить источники. Повторите попытку.",
    permission: "У вас нет прав на управление источниками.",
    remove: "Удалить",
    removeError: "Не удалось удалить источник. Повторите попытку.",
    removeTitle: "Удалить источник?",
    selected: "Выбранный источник",
    sourceFile: "Файл источника",
    title: "Источники",
    upload: "Загрузить источник",
    uploadError: "Не удалось загрузить источник. Повторите попытку.",
    uploading: "Загрузка…",
  },
}

const defaultGateway = createSourcesGateway()

function canManageSources(role: WorkspaceRole): boolean {
  return role === "owner" || role === "admin"
}

export function SourcesPage({
  gateway = defaultGateway,
  locale,
  workspaceId,
  workspaceRole,
}: {
  readonly gateway?: SourcesGateway
  readonly locale: SaasLocale
  readonly workspaceId: string
  readonly workspaceRole: WorkspaceRole
}): React.JSX.Element {
  const labels = copy[locale]
  const [state, setState] = useState<SourcesState>(() =>
    canManageSources(workspaceRole) ? { kind: "loading" } : { kind: "ready", documents: [] },
  )
  const [file, setFile] = useState<File | null>(null)
  const [uploadPending, setUploadPending] = useState(false)
  const [removal, setRemoval] = useState<SourceDocument | null>(null)
  const [notice, setNotice] = useState<"remove" | "upload" | null>(null)

  useEffect(() => {
    if (!canManageSources(workspaceRole)) return
    let active = true
    void gateway
      .list(workspaceId)
      .then((documents) => {
        if (active) setState({ kind: "ready", documents })
      })
      .catch(() => {
        if (active) setState({ kind: "error" })
      })
    return (): void => {
      active = false
    }
  }, [gateway, workspaceId, workspaceRole])

  if (!canManageSources(workspaceRole)) {
    return <p className="rs-saas-permission">{labels.permission}</p>
  }
  if (state.kind === "loading") {
    return (
      <p aria-busy="true" className="rs-saas-permission">
        {labels.title}
      </p>
    )
  }
  if (state.kind === "error") {
    return (
      <p role="alert" className="rs-saas-notice rs-saas-notice--error">
        {labels.loadError}
      </p>
    )
  }

  const upload = async (event: React.FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault()
    if (file === null) return
    setNotice(null)
    setUploadPending(true)
    try {
      await gateway.upload(workspaceId, file)
      setState({ kind: "ready", documents: await gateway.list(workspaceId) })
      setFile(null)
    } catch {
      setNotice("upload")
    } finally {
      setUploadPending(false)
    }
  }

  const remove = async (): Promise<void> => {
    if (removal === null) return
    setNotice(null)
    try {
      await gateway.remove(workspaceId, removal.doc_id)
      setState({
        kind: "ready",
        documents: state.documents.filter(({ doc_id }) => doc_id !== removal.doc_id),
      })
      setRemoval(null)
    } catch {
      setNotice("remove")
    }
  }

  return (
    <section className="rs-sources">
      <header className="rs-sources__heading">
        <span className="rs-saas-eyebrow">RAG-STUDIO</span>
        <h1>{labels.title}</h1>
        <p>{labels.description}</p>
      </header>
      {notice !== null ? (
        <p role="alert" className="rs-saas-notice rs-saas-notice--error">
          {notice === "upload" ? labels.uploadError : labels.removeError}
        </p>
      ) : null}
      <Card>
        <CardHeader>
          <Upload aria-hidden="true" size={20} />
          <CardTitle>{labels.upload}</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="rs-saas-form" onSubmit={(event) => void upload(event)}>
            <div className="rs-saas-field">
              <Label htmlFor="saas-source-file">{labels.sourceFile}</Label>
              <Input
                accept=".csv,.docx,.md,.pdf,.txt"
                disabled={uploadPending}
                id="saas-source-file"
                onChange={(event) => setFile(event.currentTarget.files?.item(0) ?? null)}
                type="file"
              />
            </div>
            {file !== null ? (
              <p>
                {labels.selected}: {file.name}
              </p>
            ) : null}
            <Button disabled={file === null || uploadPending} type="submit">
              <Upload aria-hidden="true" size={17} />
              {uploadPending ? labels.uploading : labels.upload}
            </Button>
          </form>
        </CardContent>
      </Card>
      <div className="rs-sources__records">
        {state.documents.length === 0 ? (
          <Card>
            <CardContent>
              <p className="rs-people__empty">{labels.empty}</p>
            </CardContent>
          </Card>
        ) : (
          state.documents.map((document) => (
            <Card key={document.doc_id}>
              <CardHeader>
                <FileText aria-hidden="true" size={20} />
                <CardTitle>{document.filename}</CardTitle>
              </CardHeader>
              <CardContent className="rs-sources__record">
                <p>{document.chunk_count}</p>
                <Button
                  aria-label={`${labels.remove} ${document.filename}`}
                  onClick={() => setRemoval(document)}
                  variant="secondary"
                >
                  <Trash2 aria-hidden="true" size={16} />
                  {labels.remove}
                </Button>
              </CardContent>
            </Card>
          ))
        )}
      </div>
      {removal !== null ? (
        <Card className="rs-sources__confirmation" role="dialog" aria-modal="true">
          <CardHeader>
            <CardTitle>{labels.removeTitle}</CardTitle>
          </CardHeader>
          <CardContent>
            <p>{labels.confirmRemoval}</p>
            <div className="rs-chatbots__actions">
              <Button onClick={() => setRemoval(null)} variant="secondary">
                {locale === "ru" ? "Отмена" : "Cancel"}
              </Button>
              <Button onClick={() => void remove()}>{labels.confirm}</Button>
            </div>
          </CardContent>
        </Card>
      ) : null}
    </section>
  )
}

import { Bot, MessageSquare, Pencil, Plus, Power, Trash2 } from "lucide-react"
import { useEffect, useState } from "react"

import "./chatbots.css"
import { ApiError } from "../../../api/errors"
import { Button } from "../../../components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "../../../components/ui/dialog"
import { Input } from "../../../components/ui/input"
import { Label } from "../../../components/ui/label"
import { Textarea } from "../../../components/ui/textarea"
import type { SaasLocale, WorkspaceRole } from "../model"
import { TestChatSurface } from "../test-chat/TestChatSurface"
import type { TestChatGateway, TestChatStreamGateway } from "../test-chat/test-chat-api"
import {
  type ChatbotDefinitionInput,
  type ChatbotGateway,
  type ChatbotRecord,
  createChatbotGateway,
} from "./chatbots-api"
import { getChatbotsCopy } from "./chatbots-copy"

type PageState =
  | { readonly kind: "loading" }
  | { readonly kind: "error" }
  | { readonly kind: "ready"; readonly records: readonly ChatbotRecord[] }

type EditorState =
  | { readonly kind: "create" }
  | { readonly kind: "edit"; readonly record: ChatbotRecord }

type ConfirmationState = {
  readonly kind: "disable" | "archive"
  readonly record: ChatbotRecord
}

type ChatbotEditorProps = {
  readonly editor: EditorState
  readonly locale: SaasLocale
  readonly pending: boolean
  readonly onClose: () => void
  readonly onSubmit: (input: ChatbotDefinitionInput) => Promise<void>
}

type EditorErrors = Readonly<
  Partial<Record<"modelName" | "nameEn" | "nameRu" | "provider", string>>
>

const defaultGateway = createChatbotGateway()
const providerPattern = /^[a-z][a-z0-9_-]*$/
const modelPattern = /^[A-Za-z0-9][A-Za-z0-9._:/-]*$/

function definitionErrors(
  input: ChatbotDefinitionInput,
  labels: ReturnType<typeof getChatbotsCopy>,
): EditorErrors {
  return {
    ...(input.name.en.trim() === "" ? { nameEn: labels.englishNameError } : {}),
    ...(input.name.ru.trim() === "" ? { nameRu: labels.russianNameError } : {}),
    ...(!providerPattern.test(input.provider) ? { provider: labels.providerError } : {}),
    ...(!modelPattern.test(input.model_name) ? { modelName: labels.modelError } : {}),
  }
}

function ChatbotEditor({
  editor,
  locale,
  onClose,
  onSubmit,
  pending,
}: ChatbotEditorProps): React.JSX.Element {
  const labels = getChatbotsCopy(locale)
  const initial = editor.kind === "edit" ? editor.record : null
  const [nameEn, setNameEn] = useState(initial?.name.en ?? "")
  const [nameRu, setNameRu] = useState(initial?.name.ru ?? "")
  const [instructionsEn, setInstructionsEn] = useState(initial?.instructions.en ?? "")
  const [instructionsRu, setInstructionsRu] = useState(initial?.instructions.ru ?? "")
  const [provider, setProvider] = useState(initial?.provider ?? "")
  const [modelName, setModelName] = useState(initial?.model_name ?? "")
  const [errors, setErrors] = useState<EditorErrors>({})

  const submit = (event: React.FormEvent<HTMLFormElement>): void => {
    event.preventDefault()
    const input: ChatbotDefinitionInput = {
      name: { en: nameEn, ru: nameRu },
      instructions: { en: instructionsEn, ru: instructionsRu },
      provider,
      model_name: modelName,
      source_scope: "workspace_all",
    }
    const nextErrors = definitionErrors(input, labels)
    setErrors(nextErrors)
    if (Object.keys(nextErrors).length > 0) return
    void onSubmit(input)
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="rs-saas-editor">
        <DialogTitle>
          {editor.kind === "create" ? labels.createTitle : labels.editTitle}
        </DialogTitle>
        <DialogDescription>{labels.sourceScope}</DialogDescription>
        <form className="rs-saas-form" onSubmit={submit}>
          <div className="rs-saas-field">
            <Label htmlFor="chatbot-name-en">{labels.englishName}</Label>
            <Input
              aria-describedby={errors.nameEn === undefined ? undefined : "chatbot-name-en-error"}
              aria-invalid={errors.nameEn === undefined ? undefined : true}
              disabled={pending}
              id="chatbot-name-en"
              maxLength={120}
              onChange={(event) => setNameEn(event.currentTarget.value)}
              required
              value={nameEn}
            />
            {errors.nameEn === undefined ? null : (
              <p className="rs-saas-field-error" id="chatbot-name-en-error" role="alert">
                {errors.nameEn}
              </p>
            )}
          </div>
          <div className="rs-saas-field">
            <Label htmlFor="chatbot-name-ru">{labels.russianName}</Label>
            <Input
              aria-describedby={errors.nameRu === undefined ? undefined : "chatbot-name-ru-error"}
              aria-invalid={errors.nameRu === undefined ? undefined : true}
              disabled={pending}
              id="chatbot-name-ru"
              maxLength={120}
              onChange={(event) => setNameRu(event.currentTarget.value)}
              required
              value={nameRu}
            />
            {errors.nameRu === undefined ? null : (
              <p className="rs-saas-field-error" id="chatbot-name-ru-error" role="alert">
                {errors.nameRu}
              </p>
            )}
          </div>
          <div className="rs-saas-field">
            <Label htmlFor="chatbot-instructions-en">{labels.englishInstructions}</Label>
            <Textarea
              disabled={pending}
              id="chatbot-instructions-en"
              maxLength={8_000}
              onChange={(event) => setInstructionsEn(event.currentTarget.value)}
              value={instructionsEn}
            />
          </div>
          <div className="rs-saas-field">
            <Label htmlFor="chatbot-instructions-ru">{labels.russianInstructions}</Label>
            <Textarea
              disabled={pending}
              id="chatbot-instructions-ru"
              maxLength={8_000}
              onChange={(event) => setInstructionsRu(event.currentTarget.value)}
              value={instructionsRu}
            />
          </div>
          <div className="rs-saas-field">
            <Label htmlFor="chatbot-provider">{labels.provider}</Label>
            <Input
              aria-describedby={
                errors.provider === undefined ? undefined : "chatbot-provider-error"
              }
              aria-invalid={errors.provider === undefined ? undefined : true}
              disabled={pending}
              id="chatbot-provider"
              maxLength={40}
              onChange={(event) => setProvider(event.currentTarget.value)}
              pattern="[a-z][a-z0-9_-]*"
              required
              value={provider}
            />
            {errors.provider === undefined ? null : (
              <p className="rs-saas-field-error" id="chatbot-provider-error" role="alert">
                {errors.provider}
              </p>
            )}
          </div>
          <div className="rs-saas-field">
            <Label htmlFor="chatbot-model">{labels.model}</Label>
            <Input
              aria-describedby={errors.modelName === undefined ? undefined : "chatbot-model-error"}
              aria-invalid={errors.modelName === undefined ? undefined : true}
              disabled={pending}
              id="chatbot-model"
              maxLength={120}
              onChange={(event) => setModelName(event.currentTarget.value)}
              required
              value={modelName}
            />
            {errors.modelName === undefined ? null : (
              <p className="rs-saas-field-error" id="chatbot-model-error" role="alert">
                {errors.modelName}
              </p>
            )}
          </div>
          <Button disabled={pending} type="submit">
            {pending ? labels.saving : editor.kind === "create" ? labels.create : labels.save}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function replaceRecord(
  records: readonly ChatbotRecord[],
  next: ChatbotRecord,
): readonly ChatbotRecord[] {
  return records.map((record) => (record.id === next.id ? next : record))
}

export function ChatbotsPage({
  gateway = defaultGateway,
  locale,
  testChatGateway,
  testChatStreamGateway,
  workspaceId,
  workspaceRole,
}: {
  readonly gateway?: ChatbotGateway
  readonly locale: SaasLocale
  readonly testChatGateway?: TestChatGateway
  readonly testChatStreamGateway?: TestChatStreamGateway
  readonly workspaceId: string
  readonly workspaceRole: WorkspaceRole
}): React.JSX.Element {
  const labels = getChatbotsCopy(locale)
  const canManage = workspaceRole === "owner" || workspaceRole === "admin"
  const [state, setState] = useState<PageState>({ kind: "loading" })
  const [editor, setEditor] = useState<EditorState | null>(null)
  const [confirmation, setConfirmation] = useState<ConfirmationState | null>(null)
  const [testing, setTesting] = useState<ChatbotRecord | null>(null)
  const [mutationPending, setMutationPending] = useState(false)
  const [notice, setNotice] = useState<"conflict" | "error" | null>(null)

  useEffect(() => {
    let active = true
    void gateway
      .list(workspaceId)
      .then((records) => {
        if (active) setState({ kind: "ready", records })
      })
      .catch(() => {
        if (active) setState({ kind: "error" })
      })
    return (): void => {
      active = false
    }
  }, [gateway, workspaceId])

  const mutationFailed = (error: unknown): void => {
    setNotice(error instanceof ApiError && error.status === 409 ? "conflict" : "error")
  }

  const save = async (input: ChatbotDefinitionInput): Promise<void> => {
    if (state.kind !== "ready" || editor === null) return
    setMutationPending(true)
    setNotice(null)
    try {
      const saved =
        editor.kind === "create"
          ? await gateway.create(workspaceId, input)
          : await gateway.update(workspaceId, editor.record.id, {
              ...input,
              version: editor.record.version,
            })
      setState({
        kind: "ready",
        records:
          editor.kind === "create"
            ? [...state.records, saved]
            : replaceRecord(state.records, saved),
      })
      setEditor(null)
    } catch (error) {
      mutationFailed(error)
    } finally {
      setMutationPending(false)
    }
  }

  const confirmLifecycle = async (): Promise<void> => {
    if (state.kind !== "ready" || confirmation === null) return
    const current = confirmation.record
    setMutationPending(true)
    setNotice(null)
    try {
      if (confirmation.kind === "disable") {
        const disabled = await gateway.disable(workspaceId, current.id, current.version)
        setState({
          kind: "ready",
          records: replaceRecord(state.records, {
            ...current,
            status: disabled.status,
            version: disabled.version,
          }),
        })
      } else {
        await gateway.archive(workspaceId, current.id, current.version)
        setState({
          kind: "ready",
          records: state.records.filter(({ id }) => id !== current.id),
        })
      }
      setConfirmation(null)
    } catch (error) {
      mutationFailed(error)
    } finally {
      setMutationPending(false)
    }
  }

  if (state.kind === "loading") {
    return (
      <p className="rs-saas-permission" aria-busy="true">
        {labels.loading}
      </p>
    )
  }
  if (state.kind === "error") {
    return (
      <p className="rs-saas-notice rs-saas-notice--error" role="alert">
        {labels.loadError}
      </p>
    )
  }

  return (
    <section className="rs-chatbots">
      <header className="rs-chatbots__heading">
        <div>
          <span className="rs-saas-eyebrow">RAG-STUDIO</span>
          <h1>{labels.title}</h1>
          <p>{labels.description}</p>
        </div>
        {canManage ? (
          <Button onClick={() => setEditor({ kind: "create" })}>
            <Plus aria-hidden="true" size={17} />
            {labels.newChatbot}
          </Button>
        ) : null}
      </header>
      {!canManage ? <p className="rs-saas-permission">{labels.readOnly}</p> : null}
      {notice !== null ? (
        <p className="rs-saas-notice rs-saas-notice--error" role="alert">
          {notice === "conflict" ? labels.conflict : labels.mutationError}
        </p>
      ) : null}
      {state.records.length === 0 ? (
        <Card>
          <CardHeader>
            <Bot aria-hidden="true" size={20} />
            <CardTitle>{labels.emptyTitle}</CardTitle>
          </CardHeader>
          <CardContent>
            <p>{labels.emptyBody}</p>
          </CardContent>
        </Card>
      ) : (
        <div className="rs-chatbots__grid">
          {state.records.map((record) => {
            const name = record.name[locale]
            return (
              <Card key={record.id}>
                <CardHeader>
                  <Bot aria-hidden="true" size={20} />
                  <CardTitle>{name}</CardTitle>
                </CardHeader>
                <CardContent>
                  <p>
                    {record.provider} · {record.model_name}
                  </p>
                  <p>
                    {record.status === "enabled" ? labels.enabled : labels.disabled} ·{" "}
                    {labels.version} {record.version}
                  </p>
                  {canManage ? (
                    <div className="rs-chatbots__actions">
                      {record.status === "enabled" &&
                      testChatGateway !== undefined &&
                      testChatStreamGateway !== undefined ? (
                        <Button
                          aria-label={`${locale === "ru" ? "Тест" : "Test"} ${name}`}
                          variant="secondary"
                          onClick={() => setTesting(record)}
                        >
                          <MessageSquare aria-hidden="true" size={16} />
                          {locale === "ru" ? "Тест" : "Test"}
                        </Button>
                      ) : null}
                      <Button
                        aria-label={`${labels.edit} ${name}`}
                        variant="secondary"
                        onClick={() => setEditor({ kind: "edit", record })}
                      >
                        <Pencil aria-hidden="true" size={16} />
                        {labels.edit}
                      </Button>
                      {record.status === "enabled" ? (
                        <Button
                          aria-label={`${labels.disable} ${name}`}
                          variant="secondary"
                          onClick={() => setConfirmation({ kind: "disable", record })}
                        >
                          <Power aria-hidden="true" size={16} />
                          {labels.disable}
                        </Button>
                      ) : null}
                      <Button
                        aria-label={`${labels.delete} ${name}`}
                        variant="secondary"
                        onClick={() => setConfirmation({ kind: "archive", record })}
                      >
                        <Trash2 aria-hidden="true" size={16} />
                        {labels.delete}
                      </Button>
                    </div>
                  ) : null}
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}
      {editor !== null ? (
        <ChatbotEditor
          editor={editor}
          locale={locale}
          onClose={() => setEditor(null)}
          onSubmit={save}
          pending={mutationPending}
        />
      ) : null}
      {confirmation !== null ? (
        <Dialog open onOpenChange={(open) => !open && setConfirmation(null)}>
          <DialogContent>
            <DialogTitle>
              {confirmation.kind === "disable" ? labels.disableTitle : labels.deleteTitle}
            </DialogTitle>
            <DialogDescription>
              {confirmation.kind === "disable" ? labels.disableBody : labels.deleteBody}
            </DialogDescription>
            <div className="rs-chatbots__actions">
              <Button
                variant="secondary"
                disabled={mutationPending}
                onClick={() => setConfirmation(null)}
              >
                {labels.cancel}
              </Button>
              <Button disabled={mutationPending} onClick={() => void confirmLifecycle()}>
                {confirmation.kind === "disable" ? labels.confirmDisable : labels.confirmDelete}
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      ) : null}
      {testing !== null && testChatGateway !== undefined && testChatStreamGateway !== undefined ? (
        <Dialog open onOpenChange={(open) => !open && setTesting(null)}>
          <DialogContent className="rs-test-chat-dialog">
            <DialogTitle>
              {locale === "ru" ? "Тест чатбота" : "Test chatbot"}: {testing.name[locale]}
            </DialogTitle>
            <DialogDescription>
              {locale === "ru"
                ? "Приватный тест внутри выбранного рабочего пространства."
                : "A private test inside the selected workspace."}
            </DialogDescription>
            <TestChatSurface
              chatbotId={testing.id}
              gateway={testChatGateway}
              locale={locale}
              streamGateway={testChatStreamGateway}
              workspaceId={workspaceId}
            />
          </DialogContent>
        </Dialog>
      ) : null}
    </section>
  )
}

import { Globe2, RefreshCw } from "lucide-react"
import { type FormEvent, useCallback, useEffect, useState } from "react"

import { ApiError, isAbortError } from "../../api/errors"
import { useLocaleContext } from "../../app/locale-provider"
import { Button } from "../../components/ui/button"
import { Card, CardContent, CardHeader } from "../../components/ui/card"
import { Input } from "../../components/ui/input"
import { Label } from "../../components/ui/label"
import { Skeleton } from "../../components/ui/skeleton"
import type { ChatGateway, ChatStreamGateway } from "../chat/model"
import { LocalWidgetPreview } from "./LocalWidgetPreview"
import { PublicationReadyCard } from "./PublicationReadyCard"
import {
  createPublicationGateway,
  type PublicationGateway,
  type PublicationProjection,
  parseExactOrigin,
  type WidgetState,
} from "./publication-api"
import "./publication.css"

const defaultGateway = createPublicationGateway()

type LoadState =
  | { readonly kind: "loading" }
  | { readonly kind: "unpublished" }
  | { readonly kind: "ready"; readonly projection: WidgetState }
  | { readonly kind: "error" }

type Action = "publish" | "enable" | "disable" | "revoke"

async function defaultCopyText(text: string): Promise<void> {
  await navigator.clipboard.writeText(text)
}

export function WidgetPublicationPage({
  applicationOrigin = globalThis.location.origin,
  copyText = defaultCopyText,
  gateway = defaultGateway,
  chatGateway,
  chatStreamGateway,
}: {
  readonly applicationOrigin?: string | undefined
  readonly copyText?: ((text: string) => Promise<void>) | undefined
  readonly gateway?: PublicationGateway | undefined
  readonly chatGateway?: ChatGateway | undefined
  readonly chatStreamGateway?: ChatStreamGateway | undefined
}): React.JSX.Element {
  const { locale, t } = useLocaleContext()
  const [loadState, setLoadState] = useState<LoadState>({ kind: "loading" })
  const [origin, setOrigin] = useState("")
  const [originInvalid, setOriginInvalid] = useState(false)
  const [action, setAction] = useState<Action | null>(null)
  const [actionFailed, setActionFailed] = useState(false)
  const [copied, setCopied] = useState(false)

  const load = useCallback(
    async (signal?: AbortSignal): Promise<void> => {
      setLoadState({ kind: "loading" })
      try {
        const projection = await gateway.load(signal)
        if (!("mode" in projection)) setOrigin(projection.allowed_origin)
        setLoadState({ kind: "ready", projection })
      } catch (error) {
        if (isAbortError(error)) return
        if (error instanceof ApiError && error.status === 404) {
          setLoadState({ kind: "unpublished" })
          return
        }
        if (error instanceof Error) {
          setLoadState({ kind: "error" })
          return
        }
        throw error
      }
    },
    [gateway],
  )

  useEffect(() => {
    const request = new AbortController()
    void load(request.signal)
    return () => request.abort()
  }, [load])

  const commit = async (nextAction: Action, operation: () => Promise<PublicationProjection>) => {
    if (action !== null) return
    setAction(nextAction)
    setActionFailed(false)
    try {
      const projection = await operation()
      setOrigin(projection.allowed_origin)
      setLoadState({ kind: "ready", projection })
    } catch (error) {
      if (error instanceof Error) setActionFailed(true)
      else throw error
    } finally {
      setAction(null)
    }
  }

  const publish = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault()
    const parsed = parseExactOrigin(origin)
    if (!parsed.ok) {
      setOriginInvalid(true)
      return
    }
    setOriginInvalid(false)
    void commit("publish", () => gateway.publish(parsed.origin))
  }

  if (loadState.kind === "loading") {
    return (
      <section aria-busy="true" className="rs-publication" lang={locale} role="status">
        <span className="rs-visually-hidden">{t("publication_loading")}</span>
        <Skeleton className="rs-publication__skeleton" />
      </section>
    )
  }

  if (loadState.kind === "error") {
    return (
      <section className="rs-publication rs-publication__recovery" lang={locale}>
        <div role="alert">
          <h2>{t("publication_unavailable")}</h2>
          <p>{t("publication_unavailable_detail")}</p>
        </div>
        <Button onClick={() => void load()} variant="secondary">
          <RefreshCw aria-hidden="true" size={16} />
          {t("publication_retry")}
        </Button>
      </section>
    )
  }

  const projection = loadState.kind === "ready" ? loadState.projection : null
  const busy = action !== null
  const localDemo = projection !== null && "mode" in projection

  return (
    <section
      aria-labelledby="publication-section-title"
      className="rs-publication"
      data-testid="publication-locale"
      lang={locale}
    >
      <header className="rs-publication__intro">
        <p>{t(localDemo ? "publication_local_preview_badge" : "publication_eyebrow")}</p>
        <h2 id="publication-section-title">
          {t(localDemo ? "publication_local_preview_page_title" : "publication_title")}
        </h2>
        <span>
          {t(localDemo ? "publication_local_preview_page_detail" : "publication_description")}
        </span>
      </header>

      {projection !== null && "mode" in projection ? (
        <LocalWidgetPreview gateway={chatGateway} streamGateway={chatStreamGateway} />
      ) : projection === null ? (
        <Card>
          <CardHeader className="rs-publication__card-header">
            <Globe2 aria-hidden="true" size={20} />
            <h3>{t("publication_origin_title")}</h3>
          </CardHeader>
          <CardContent>
            <form className="rs-publication__form" noValidate onSubmit={publish}>
              <Label htmlFor="publication-origin">{t("publication_origin_label")}</Label>
              <Input
                aria-describedby="publication-origin-help publication-origin-error"
                aria-invalid={originInvalid}
                autoComplete="url"
                id="publication-origin"
                onChange={(event) => {
                  setOrigin(event.target.value)
                  setOriginInvalid(false)
                  setActionFailed(false)
                }}
                placeholder={t("publication_origin_placeholder")}
                value={origin}
              />
              <p className="rs-publication__helper" id="publication-origin-help">
                {t("publication_origin_helper")}
              </p>
              {originInvalid ? (
                <p id="publication-origin-error" role="alert">
                  {t("publication_origin_invalid")}
                </p>
              ) : null}
              {actionFailed ? <p role="alert">{t("publication_action_failed")}</p> : null}
              <Button disabled={busy} type="submit">
                <Globe2 aria-hidden="true" size={16} />
                {action === "publish" ? t("publication_saving") : t("publication_publish")}
              </Button>
            </form>
          </CardContent>
        </Card>
      ) : (
        <PublicationReadyCard
          actionFailed={actionFailed}
          applicationOrigin={applicationOrigin}
          busy={busy}
          copied={copied}
          onCopy={(snippet) => {
            void copyText(snippet).then(
              () => setCopied(true),
              () => setActionFailed(true),
            )
          }}
          onDisable={() => void commit("disable", gateway.disable)}
          onEnable={() => void commit("enable", () => gateway.publish(projection.allowed_origin))}
          onRevoke={() => void commit("revoke", gateway.revoke)}
          projection={projection}
        />
      )}
    </section>
  )
}

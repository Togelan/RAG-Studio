import { Ban, Check, Clipboard, RotateCcw, Trash2 } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { useLocaleContext } from "../../app/locale-provider"
import { Button } from "../../components/ui/button"
import { Card, CardContent } from "../../components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from "../../components/ui/dialog"
import {
  buildEmbedSnippet,
  MONTHLY_WIDGET_MESSAGE_LIMIT,
  type PublicationProjection,
} from "./publication-api"

const statusKeys = {
  disabled: "publication_status_disabled",
  enabled: "publication_status_enabled",
  revoked: "publication_status_revoked",
} as const

export function PublicationReadyCard({
  actionFailed,
  applicationOrigin,
  busy,
  copied,
  onCopy,
  onDisable,
  onEnable,
  onRevoke,
  projection,
}: {
  readonly actionFailed: boolean
  readonly applicationOrigin: string
  readonly busy: boolean
  readonly copied: boolean
  readonly onCopy: (snippet: string) => void
  readonly onDisable: () => void
  readonly onEnable: () => void
  readonly onRevoke: () => void
  readonly projection: PublicationProjection
}): React.JSX.Element {
  const { t } = useLocaleContext()
  const snippet = buildEmbedSnippet(projection.public_key, applicationOrigin)
  const [revokeOpen, setRevokeOpen] = useState(false)
  const statusRef = useRef<HTMLElement>(null)
  const previousState = useRef(projection.state)

  useEffect(() => {
    if (previousState.current !== projection.state) statusRef.current?.focus()
    previousState.current = projection.state
  }, [projection.state])

  return (
    <Card>
      <CardContent className="rs-publication__content">
        <dl className="rs-publication__status">
          <div>
            <dt>{t("publication_status_label")}</dt>
            <dd
              aria-live="polite"
              data-status={projection.state}
              ref={statusRef}
              role="status"
              tabIndex={-1}
            >
              {t(statusKeys[projection.state])}
            </dd>
          </div>
          <div>
            <dt>{t("publication_origin_label")}</dt>
            <dd>{projection.allowed_origin}</dd>
          </div>
          <div>
            <dt>{t("publication_quota_label")}</dt>
            <dd>
              <strong>{MONTHLY_WIDGET_MESSAGE_LIMIT}</strong> {t("publication_quota_period")}
            </dd>
          </div>
        </dl>
        {projection.state !== "revoked" ? (
          <figure className="rs-publication__snippet">
            <figcaption>{t("publication_snippet_label")}</figcaption>
            <code id="publication-snippet">{snippet}</code>
            <Button disabled={busy} onClick={() => onCopy(snippet)} variant="secondary">
              <Clipboard aria-hidden="true" size={16} />
              {t("publication_copy_snippet")}
            </Button>
            {copied ? (
              <p className="rs-publication__copied" role="status">
                <Check aria-hidden="true" size={16} /> {t("publication_copied")}
              </p>
            ) : null}
          </figure>
        ) : null}
        {actionFailed ? <p role="alert">{t("publication_action_failed")}</p> : null}
        <div className="rs-publication__actions">
          {projection.state === "enabled" ? (
            <Button disabled={busy} onClick={onDisable} variant="secondary">
              <Ban aria-hidden="true" size={16} /> {t("publication_disable")}
            </Button>
          ) : null}
          {projection.state === "disabled" ? (
            <Button disabled={busy} onClick={onEnable}>
              <RotateCcw aria-hidden="true" size={16} /> {t("publication_enable")}
            </Button>
          ) : null}
          {projection.state !== "revoked" ? (
            <Dialog onOpenChange={setRevokeOpen} open={revokeOpen}>
              <DialogTrigger asChild>
                <Button disabled={busy} variant="danger">
                  <Trash2 aria-hidden="true" size={16} /> {t("publication_revoke")}
                </Button>
              </DialogTrigger>
              <DialogContent closeLabel={t("publication_close_dialog")}>
                <DialogTitle>{t("publication_revoke_confirm")}</DialogTitle>
                <DialogDescription>{t("publication_revoke_detail")}</DialogDescription>
                <div className="rs-publication__actions">
                  <Button onClick={() => setRevokeOpen(false)} variant="secondary">
                    {t("publication_cancel")}
                  </Button>
                  <Button
                    onClick={() => {
                      setRevokeOpen(false)
                      onRevoke()
                    }}
                    variant="danger"
                  >
                    {t("publication_revoke_confirm_action")}
                  </Button>
                </div>
              </DialogContent>
            </Dialog>
          ) : null}
        </div>
      </CardContent>
    </Card>
  )
}

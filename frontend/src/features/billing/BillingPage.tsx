import { CreditCard, ExternalLink, RefreshCw, ShieldCheck } from "lucide-react"
import { useCallback, useEffect, useState } from "react"

import { isAbortError } from "../../api/errors"
import { useLocaleContext } from "../../app/locale-provider"
import { Button } from "../../components/ui/button"
import { Card, CardContent, CardHeader } from "../../components/ui/card"
import { Skeleton } from "../../components/ui/skeleton"
import { type BillingGateway, type BillingState, createBillingGateway } from "./billing-api"
import "./billing.css"

const defaultGateway = createBillingGateway()

type LoadState =
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly projection: BillingState }
  | { readonly kind: "error" }

type HostedAction = "checkout" | "portal"

const statusKeys = {
  active: "billing_status_active",
  canceled: "billing_status_canceled",
  incomplete: "billing_status_incomplete",
  none: "billing_status_none",
  past_due: "billing_status_past_due",
  unpaid: "billing_status_unpaid",
} as const

function defaultHostedNavigation(url: string): void {
  window.location.assign(url)
}

export function BillingPage({
  gateway = defaultGateway,
  navigateToHosted = defaultHostedNavigation,
}: {
  readonly gateway?: BillingGateway | undefined
  readonly navigateToHosted?: ((url: string) => void) | undefined
}): React.JSX.Element {
  const { locale, t } = useLocaleContext()
  const [loadState, setLoadState] = useState<LoadState>({ kind: "loading" })
  const [hostedAction, setHostedAction] = useState<HostedAction | null>(null)
  const [actionFailed, setActionFailed] = useState(false)

  const load = useCallback(
    async (signal?: AbortSignal): Promise<void> => {
      setLoadState({ kind: "loading" })
      try {
        setLoadState({ kind: "ready", projection: await gateway.load(signal) })
      } catch (error) {
        if (isAbortError(error)) return
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

  const openHosted = async (action: HostedAction): Promise<void> => {
    if (hostedAction !== null) return
    setHostedAction(action)
    setActionFailed(false)
    try {
      const destination = action === "checkout" ? await gateway.checkout() : await gateway.portal()
      navigateToHosted(destination.url)
    } catch (error) {
      if (error instanceof Error) {
        setActionFailed(true)
        setHostedAction(null)
        return
      }
      throw error
    }
  }

  if (loadState.kind === "loading") {
    return (
      <section aria-busy="true" className="rs-billing" lang={locale} role="status">
        <span className="rs-visually-hidden">{t("billing_loading")}</span>
        <Skeleton className="rs-billing__skeleton" />
      </section>
    )
  }

  if (loadState.kind === "error") {
    return (
      <section className="rs-billing rs-billing__recovery" lang={locale}>
        <div role="alert">
          <h2>{t("billing_unavailable")}</h2>
          <p>{t("billing_unavailable_detail")}</p>
        </div>
        <Button onClick={() => void load()} variant="secondary">
          <RefreshCw aria-hidden="true" size={16} />
          {t("billing_retry")}
        </Button>
      </section>
    )
  }

  const { projection } = loadState
  if ("mode" in projection) {
    const price = `$${projection.plan.amount_usd_cents / 100} ${projection.plan.currency}`
    return (
      <section
        aria-labelledby="billing-demo-title"
        className="rs-billing"
        data-testid="billing-locale"
        lang={locale}
      >
        <header className="rs-billing__intro">
          <p>{t("billing_eyebrow")}</p>
          <h2 id="billing-demo-title">{t("billing_local_demo_title")}</h2>
          <span>{t("billing_local_demo_detail")}</span>
        </header>
        <Card className="rs-billing__card">
          <CardHeader className="rs-billing__card-header">
            <div className="rs-billing__plan-mark" aria-hidden="true">
              <ShieldCheck size={20} />
            </div>
            <div>
              <p className="rs-billing__price">
                <strong>{price}</strong>
                <span>{t("billing_interval_month")}</span>
              </p>
              <p className="rs-billing__helper">{t("billing_local_demo_access")}</p>
            </div>
          </CardHeader>
          <CardContent className="rs-billing__content">
            <p className="rs-billing__helper">{t("billing_local_demo_no_payment")}</p>
          </CardContent>
        </Card>
      </section>
    )
  }
  const checkoutDisabled = projection.entitled || projection.pending || hostedAction !== null
  const portalDisabled = !projection.can_manage || hostedAction !== null
  const price = `$${projection.plan.amount_usd_cents / 100} ${projection.plan.currency}`

  return (
    <section
      aria-labelledby="billing-section-title"
      className="rs-billing"
      data-testid="billing-locale"
      lang={locale}
    >
      <header className="rs-billing__intro">
        <p>{t("billing_eyebrow")}</p>
        <h2 id="billing-section-title">{t("billing_plan_name")}</h2>
        <span>{t("billing_description")}</span>
      </header>
      <Card className="rs-billing__card">
        <CardHeader className="rs-billing__card-header">
          <div className="rs-billing__plan-mark" aria-hidden="true">
            <CreditCard size={20} />
          </div>
          <div>
            <p className="rs-billing__price">
              <strong>{price}</strong>
              <span>{t("billing_interval_month")}</span>
            </p>
          </div>
        </CardHeader>
        <CardContent className="rs-billing__content">
          <dl className="rs-billing__status">
            <div>
              <dt>{t("billing_status_label")}</dt>
              <dd data-status={projection.status}>{t(statusKeys[projection.status])}</dd>
            </div>
            <div>
              <dt>{t("billing_authority_label")}</dt>
              <dd>
                <ShieldCheck aria-hidden="true" size={16} />
                {t("billing_authority_verified")}
              </dd>
            </div>
          </dl>
          {actionFailed ? <p role="alert">{t("billing_action_failed")}</p> : null}
          <div className="rs-billing__actions">
            <Button disabled={checkoutDisabled} onClick={() => void openHosted("checkout")}>
              <ExternalLink aria-hidden="true" size={16} />
              {hostedAction === "checkout" ? t("billing_redirecting") : t("billing_checkout")}
            </Button>
            <Button
              disabled={portalDisabled}
              onClick={() => void openHosted("portal")}
              variant="secondary"
            >
              <ExternalLink aria-hidden="true" size={16} />
              {hostedAction === "portal" ? t("billing_redirecting") : t("billing_portal")}
            </Button>
          </div>
          <p className="rs-billing__helper">{t("billing_hosted_helper")}</p>
        </CardContent>
      </Card>
    </section>
  )
}

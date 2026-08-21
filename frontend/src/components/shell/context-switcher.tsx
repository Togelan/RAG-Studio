import { ChevronDown, Layers3 } from "lucide-react"
import type { Locale } from "../../i18n/locale-inventory"
import { type EffectiveRole, effectiveRoleLabel, getShellCopy } from "../../i18n/shell-copy"
import { Button } from "../ui/button"

export type ContextOption =
  | { readonly id: string; readonly kind: "personal" }
  | {
      readonly id: string
      readonly kind: "workspace"
      readonly name: string
      readonly role: EffectiveRole
    }

type RecoverableContextState = {
  readonly accountName?: string
  readonly availableContexts?: readonly ContextOption[] | undefined
  readonly onSelectContext?: ((contextId: string) => void) | undefined
  readonly onSignIn?: (() => void | Promise<void>) | undefined
  readonly state: "no-context" | "error" | "forbidden" | "revoked"
}

export type ContextState =
  | { readonly accountName?: string; readonly state: "loading" }
  | RecoverableContextState
  | { readonly accountName?: string; readonly state: "selection-pending" }
  | {
      readonly accountName: string
      readonly availableContexts: readonly ContextOption[]
      readonly onSelectContext?: ((contextId: string) => void) | undefined
      readonly selectedContextId: string
      readonly state: "ready"
    }

function contextName(locale: Locale, context: ContextOption): string {
  return context.kind === "personal" ? getShellCopy(locale).personalLab : context.name
}

function stateMessage(locale: Locale, state: Exclude<ContextState["state"], "ready">): string {
  const copy = getShellCopy(locale)
  switch (state) {
    case "loading":
      return copy.contextLoading
    case "no-context":
      return copy.noContext
    case "selection-pending":
      return copy.contextPending
    case "error":
      return copy.contextError
    case "forbidden":
      return copy.contextForbidden
    case "revoked":
      return copy.contextRevoked
  }
}

function ContextRecoveryActions({
  context,
  idPrefix,
  locale,
}: {
  readonly context: Exclude<
    ContextState,
    { readonly state: "ready" | "loading" | "selection-pending" }
  >
  readonly idPrefix: string
  readonly locale: Locale
}): React.JSX.Element | null {
  const copy = getShellCopy(locale)
  const availableContexts = context.availableContexts ?? []

  if (context.onSelectContext !== undefined && availableContexts.length > 0) {
    return (
      <label
        className="rs-context-switcher__recovery-control"
        htmlFor={`${idPrefix}-recovery-selector`}
      >
        <span>{copy.selectAvailableContext}</span>
        <select
          aria-label={copy.selectAvailableContext}
          defaultValue=""
          id={`${idPrefix}-recovery-selector`}
          onChange={(event) => {
            if (event.target.value !== "") context.onSelectContext?.(event.target.value)
          }}
        >
          <option disabled value="">
            {copy.selectAvailableContext}
          </option>
          {availableContexts.map((candidate) => (
            <option key={candidate.id} value={candidate.id}>
              {contextName(locale, candidate)}
            </option>
          ))}
        </select>
      </label>
    )
  }

  if (context.onSignIn !== undefined) {
    return (
      <Button
        className="rs-context-switcher__sign-in"
        onClick={() => void context.onSignIn?.()}
        variant="secondary"
      >
        {copy.signIn}
      </Button>
    )
  }

  return null
}

export function ContextStateNotice({
  context,
  locale,
}: {
  readonly context: ContextState
  readonly locale: Locale
}): React.JSX.Element | null {
  if (context.state === "ready") return null

  return (
    <p className="rs-context-switcher__status" role="status">
      {stateMessage(locale, context.state)}
    </p>
  )
}

export function ContextSwitcher({
  compact = false,
  context,
  idPrefix = "shell-context",
  locale,
}: {
  readonly compact?: boolean | undefined
  readonly context: ContextState
  readonly idPrefix?: string | undefined
  readonly locale: Locale
}): React.JSX.Element {
  const copy = getShellCopy(locale)
  const selectorId = `${idPrefix}-selector`

  if (context.state !== "ready") {
    const renderStateContent = (): React.JSX.Element => (
      <>
        <ContextStateNotice context={context} locale={locale} />
        {context.state === "loading" || context.state === "selection-pending" ? null : (
          <ContextRecoveryActions context={context} idPrefix={idPrefix} locale={locale} />
        )}
      </>
    )
    if (compact) {
      return (
        <section className="rs-context-switcher rs-context-switcher--compact rs-context-switcher--state">
          <details>
            <summary aria-label={`${copy.context}: ${stateMessage(locale, context.state)}`}>
              <Layers3 aria-hidden="true" size={18} />
              <span>{copy.context}</span>
              <ChevronDown aria-hidden="true" size={16} />
            </summary>
            <div className="rs-context-switcher__menu">{renderStateContent()}</div>
          </details>
        </section>
      )
    }

    return (
      <section className="rs-context-switcher rs-context-switcher--state">
        {renderStateContent()}
      </section>
    )
  }

  const selectedContext = context.availableContexts.find(
    (candidate) => candidate.id === context.selectedContextId,
  )

  const contextLabel =
    selectedContext === undefined ? copy.context : contextName(locale, selectedContext)
  const roleLabel =
    selectedContext?.kind === "workspace"
      ? effectiveRoleLabel(locale, selectedContext.role)
      : undefined
  const renderReadyContent = (): React.JSX.Element => (
    <>
      <label className="rs-context-switcher__control" htmlFor={selectorId}>
        <span>{copy.context}</span>
        <select
          aria-label={copy.context}
          id={selectorId}
          onChange={(event) => context.onSelectContext?.(event.target.value)}
          value={context.selectedContextId}
        >
          {context.availableContexts.map((candidate) => (
            <option key={candidate.id} value={candidate.id}>
              {contextName(locale, candidate)}
            </option>
          ))}
        </select>
      </label>
      {selectedContext !== undefined ? (
        <span className="rs-context-switcher__active-context" data-testid="active-context-label">
          {contextName(locale, selectedContext)}
        </span>
      ) : null}
      {selectedContext?.kind === "workspace" ? (
        <span className="rs-context-switcher__role rs-badge rs-badge--ai">
          {effectiveRoleLabel(locale, selectedContext.role)}
        </span>
      ) : null}
    </>
  )

  if (compact) {
    return (
      <section className="rs-context-switcher rs-context-switcher--compact">
        <details>
          <summary
            aria-label={`${copy.context}: ${contextLabel}${roleLabel === undefined ? "" : `, ${roleLabel}`}`}
          >
            <Layers3 aria-hidden="true" size={18} />
            <span>{contextLabel}</span>
            <ChevronDown aria-hidden="true" size={16} />
          </summary>
          <div className="rs-context-switcher__menu">{renderReadyContent()}</div>
        </details>
      </section>
    )
  }

  return <section className="rs-context-switcher">{renderReadyContent()}</section>
}

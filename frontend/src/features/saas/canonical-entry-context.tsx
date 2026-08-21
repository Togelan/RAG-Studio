import { useEffect, useState } from "react"
import { useLocation, useNavigate } from "react-router-dom"

import type { ContextOption, ContextState } from "../../components/shell/context-switcher"
import type { AccountContextController, AccountContextState } from "../account/account-context"
import type { AccountContext, AccountId, WorkspaceId } from "../account/account-contracts"
import type { SaasLocale } from "./model"
import { InvitationAcceptancePage } from "./workspace-lifecycle/InvitationAcceptancePage"
import { getWorkspaceLifecycleCopy } from "./workspace-lifecycle/workspace-lifecycle-copy"

export type ResolvedContext = {
  readonly accountId: AccountId
  readonly key: string
  readonly option: ContextOption
  readonly workspaceId: WorkspaceId | null
}

const unavailableCopy = {
  en: {
    description: "Choose an available context or return to the RAG-Studio home page.",
    forbidden: "Your confirmed role does not allow this task.",
    title: "Page unavailable",
  },
  ru: {
    description: "Выберите доступный контекст или вернитесь на главную страницу RAG-Studio.",
    forbidden: "Подтверждённая роль не разрешает эту операцию.",
    title: "Страница недоступна",
  },
} as const

export function neutralPageTitle(pathname: string, locale: SaasLocale): string | undefined {
  if (pathname === "/app/invitations/accept") {
    return getWorkspaceLifecycleCopy(locale).accept
  }
  return pathname === "/app/not-found" ? unavailableCopy[locale].title : undefined
}

export function contextChoices(accounts: readonly AccountContext[]): readonly ResolvedContext[] {
  return accounts.flatMap((account) => [
    {
      accountId: account.id,
      key: `account:${account.id}`,
      option: { id: `account:${account.id}`, kind: "personal" as const },
      workspaceId: null,
    },
    ...account.workspaces.map((workspace) => ({
      accountId: account.id,
      key: `workspace:${account.id}:${workspace.id}`,
      option: {
        id: `workspace:${account.id}:${workspace.id}`,
        kind: "workspace" as const,
        name: workspace.name ?? "Workspace",
        role: workspace.role,
      },
      workspaceId: workspace.id,
    })),
  ])
}

export function shellContext(
  state: AccountContextState,
  onSelect: (key: string) => void,
): ContextState {
  switch (state.kind) {
    case "idle":
    case "loading":
      return { state: "loading" }
    case "selection-pending":
      return { state: "selection-pending" }
    case "forbidden":
      return { state: "forbidden" }
    case "error":
      return { state: "error" }
    case "confirmation-required":
    case "unauthenticated":
      return { state: "no-context" }
    case "ready": {
      const choices = contextChoices(state.session.accounts)
      const account = state.session.accounts.find(
        (candidate) => candidate.id === state.session.active_account_id,
      )
      if (account === undefined) {
        return {
          availableContexts: choices.map(({ option }) => option),
          onSelectContext: onSelect,
          state: "no-context",
        }
      }
      return {
        accountName: account.label,
        availableContexts: choices.map(({ option }) => option),
        onSelectContext: onSelect,
        selectedContextId:
          state.session.workspace === null
            ? `account:${account.id}`
            : `workspace:${account.id}:${state.session.workspace.id}`,
        state: "ready",
      }
    }
  }
}

function invitationToken(locationState: unknown, search: string): string {
  if (
    typeof locationState === "object" &&
    locationState !== null &&
    "invitationToken" in locationState &&
    typeof locationState.invitationToken === "string"
  ) {
    return locationState.invitationToken
  }
  return new URLSearchParams(search).get("token") ?? ""
}

export function CanonicalInvitation({
  controller,
  locale,
}: {
  readonly controller: AccountContextController
  readonly locale: SaasLocale
}): React.JSX.Element {
  const location = useLocation()
  const navigate = useNavigate()
  const [token] = useState(() => invitationToken(location.state, location.search))

  useEffect(() => {
    if (location.search !== "" || location.state !== null) {
      navigate(location.pathname, { replace: true, state: null })
    }
  }, [location.pathname, location.search, location.state, navigate])

  return (
    <InvitationAcceptancePage
      initialToken={token}
      locale={locale}
      onAccepted={async () => {
        await controller.refresh()
        navigate("/app", { replace: true })
      }}
    />
  )
}

export function PermissionNotice({ locale }: { readonly locale: SaasLocale }): React.JSX.Element {
  return (
    <section className="rs-route-recovery" role="status">
      <h2>{unavailableCopy[locale].title}</h2>
      <p>{unavailableCopy[locale].forbidden}</p>
    </section>
  )
}

export function NotFound({ locale }: { readonly locale: SaasLocale }): React.JSX.Element {
  return (
    <section className="rs-route-recovery">
      <h2>{unavailableCopy[locale].title}</h2>
      <p>{unavailableCopy[locale].description}</p>
    </section>
  )
}

import { useEffect, useMemo, useState } from "react"
import { Navigate, useLocation, useNavigate } from "react-router-dom"

import { AppShell, type WorkspaceNavigationItem } from "../../components/shell/app-shell"
import { AccountContextController, type AccountContextState } from "../account/account-context"
import { createWorkspaceGateway, type WorkspaceGateway } from "../account/workspace-gateway"
import { type AuthMode, AuthPage } from "../auth/AuthPage"
import { type AuthGateway, createAuthGateway } from "../auth/auth-gateway"
import { PublicAuthShell } from "../auth/PublicAuthShell"
import type { HealthGateway } from "../health/health-status"
import { CanonicalWorkspaceContent } from "./CanonicalWorkspaceContent"
import { contextChoices, neutralPageTitle, shellContext } from "./canonical-entry-context"
import type { SaasLocale } from "./model"
import { getSaasCopy } from "./saas-copy"

const defaultAuthGateway = createAuthGateway()
const defaultWorkspaceGateway = createWorkspaceGateway()

function authModeForPath(pathname: string): AuthMode {
  return pathname === "/sign-up" ? "sign-up" : "sign-in"
}

function isPublicAuthPath(pathname: string): boolean {
  return pathname === "/" || pathname === "/sign-in" || pathname === "/sign-up"
}

function protectedReturnPath(pathname: string): string | null {
  return pathname === "/app" || pathname.startsWith("/app/") ? pathname : null
}

function safeReturnPath(state: unknown): string | null {
  if (typeof state !== "object" || state === null || !("returnTo" in state)) return null
  return typeof state.returnTo === "string" ? protectedReturnPath(state.returnTo) : null
}

export function SaasEntry({
  authGateway = defaultAuthGateway,
  healthGateway,
  locale,
  workspaceGateway = defaultWorkspaceGateway,
}: {
  readonly authGateway?: AuthGateway | undefined
  readonly healthGateway?: HealthGateway | undefined
  readonly locale: SaasLocale
  readonly workspaceGateway?: WorkspaceGateway | undefined
}): React.JSX.Element {
  const copy = getSaasCopy(locale)
  const location = useLocation()
  const navigate = useNavigate()
  const [controller] = useState(() => new AccountContextController(authGateway))
  const [state, setState] = useState<AccountContextState>(controller.state)
  const mode = authModeForPath(location.pathname)
  const publicAuthPath = isPublicAuthPath(location.pathname)

  useEffect(() => {
    const unsubscribe = controller.subscribe(setState)
    void controller.recover()
    return (): void => {
      unsubscribe()
      controller.dispose()
    }
  }, [controller])

  const choices = useMemo(
    () => (state.kind === "ready" ? contextChoices(state.session.accounts) : []),
    [state],
  )
  const selectContext = (key: string): void => {
    const choice = choices.find((candidate) => candidate.key === key)
    if (choice !== undefined) void controller.select(choice.accountId, choice.workspaceId)
  }

  if (state.kind === "idle" || state.kind === "loading") {
    return (
      <PublicAuthShell>
        <p aria-busy="true">{copy.submitting}</p>
      </PublicAuthShell>
    )
  }

  if (
    state.kind === "unauthenticated" ||
    state.kind === "confirmation-required" ||
    state.kind === "error"
  ) {
    if (!publicAuthPath) {
      const returnTo = protectedReturnPath(location.pathname)
      return <Navigate replace state={returnTo === null ? undefined : { returnTo }} to="/sign-in" />
    }
    const status =
      state.kind === "confirmation-required"
        ? ({ kind: "confirmation-required" } as const)
        : state.kind === "error"
          ? ({ kind: "error", message: state.message } as const)
          : ({ kind: "ready" } as const)
    return (
      <PublicAuthShell>
        <AuthPage
          locale={locale}
          mode={mode}
          onAuthenticate={async (credentials) => {
            if (mode === "sign-in") await controller.signIn(credentials)
            else await controller.signUp(credentials)
          }}
          onModeChange={(nextMode) => navigate(nextMode === "sign-up" ? "/sign-up" : "/sign-in")}
          status={status}
        />
      </PublicAuthShell>
    )
  }

  if (publicAuthPath) return <Navigate replace to={safeReturnPath(location.state) ?? "/app"} />

  const context = shellContext(state, selectContext)
  if (state.kind !== "ready") {
    return <AppShell context={context}>{null}</AppShell>
  }

  const session = state.session
  const workspaceRoot =
    session.workspace === null
      ? null
      : `/app/workspaces/${encodeURIComponent(session.workspace.id)}`
  const managesWorkspace =
    session.workspace?.role === "owner" || session.workspace?.role === "admin"
  const workspaceNavigation: readonly WorkspaceNavigationItem[] =
    workspaceRoot === null
      ? []
      : [
          { label: copy.chatbots, to: `${workspaceRoot}/chatbots` },
          ...(managesWorkspace
            ? [
                { label: copy.sources, to: `${workspaceRoot}/sources` },
                { label: copy.people, to: `${workspaceRoot}/people` },
              ]
            : []),
        ]

  return (
    <AppShell
      context={context}
      pageTitle={neutralPageTitle(location.pathname, locale)}
      user={{ identity: session.email, onSignOut: () => controller.signOut() }}
      workspaceNavigation={workspaceNavigation}
    >
      <CanonicalWorkspaceContent
        controller={controller}
        context={context}
        healthGateway={healthGateway}
        locale={locale}
        session={session}
        workspaceGateway={workspaceGateway}
      />
    </AppShell>
  )
}

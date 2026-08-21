import { useState } from "react"
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom"

import { createBrowserLocaleRuntime } from "./app/browser-locale-runtime"
import { LocaleProvider, useLocaleContext } from "./app/locale-provider"
import { WorkspaceIdSchema } from "./features/account/account-contracts"
import type { WorkspaceGateway } from "./features/account/workspace-gateway"
import type { AuthGateway } from "./features/auth/auth-gateway"
import type { HealthGateway } from "./features/health/health-status"
import { SaasEntry } from "./features/saas/SaasEntry"
import type { LocaleRuntime } from "./i18n/locale-runtime"

type CompatibilityState = {
  readonly invitationToken?: string
}

function invitationState(search: string): CompatibilityState | undefined {
  const token = new URLSearchParams(search).get("token")
  return token === null ? undefined : { invitationToken: token }
}

function retiredWorkspaceDestination(pathname: string): string {
  const match = /^\/saas\/workspaces\/([^/]+)\/(people|sources|chatbots)(.*)$/u.exec(pathname)
  if (match === null) return "/app/not-found"
  const workspaceId = WorkspaceIdSchema.safeParse(match[1])
  if (!workspaceId.success) return "/app/not-found"
  const resource = match[2]
  const suffix = match[3]
  if (resource === undefined || suffix === undefined) return "/app/not-found"
  if ((resource === "people" || resource === "sources") && suffix === "") {
    return `/app/workspaces/${workspaceId.data}/${resource}`
  }
  if (resource !== "chatbots") return "/app/not-found"
  if (suffix === "" || suffix === "/new") {
    return `/app/workspaces/${workspaceId.data}/chatbots`
  }
  return /^\/[^/]+\/(edit|test)$/u.test(suffix)
    ? `/app/workspaces/${workspaceId.data}/chatbots`
    : "/app/not-found"
}

function CompatibilityRoute(): React.JSX.Element {
  const location = useLocation()
  const destination = (() => {
    switch (location.pathname) {
      case "/saas":
        return { to: "/" }
      case "/saas/sign-in":
        return { to: "/sign-in" }
      case "/saas/sign-up":
        return { to: "/sign-up" }
      case "/saas/invitations/accept":
        return { state: invitationState(location.search), to: "/app/invitations/accept" }
      default:
        return { to: retiredWorkspaceDestination(location.pathname) }
    }
  })()
  return <Navigate replace state={destination.state} to={destination.to} />
}

function CanonicalEntry({
  authGateway,
  healthGateway,
  workspaceGateway,
}: {
  readonly authGateway?: AuthGateway | undefined
  readonly healthGateway?: HealthGateway | undefined
  readonly workspaceGateway?: WorkspaceGateway | undefined
}): React.JSX.Element {
  const { locale } = useLocaleContext()
  return (
    <SaasEntry
      authGateway={authGateway}
      healthGateway={healthGateway}
      locale={locale}
      workspaceGateway={workspaceGateway}
    />
  )
}

export function RagStudioRoutes({
  authGateway,
  healthGateway,
  workspaceGateway,
}: {
  readonly authGateway?: AuthGateway | undefined
  readonly healthGateway?: HealthGateway | undefined
  readonly workspaceGateway?: WorkspaceGateway | undefined
}): React.JSX.Element {
  const entry = (
    <CanonicalEntry
      authGateway={authGateway}
      healthGateway={healthGateway}
      workspaceGateway={workspaceGateway}
    />
  )
  return (
    <Routes>
      <Route element={<CompatibilityRoute />} path="/saas/*" />
      <Route element={entry} path="/" />
      <Route element={entry} path="/sign-in" />
      <Route element={entry} path="/sign-up" />
      <Route element={entry} path="/app/*" />
      <Route element={<Navigate replace to="/app/settings" />} path="/settings" />
      <Route element={<Navigate replace to="/app/chat" />} path="/chat" />
      <Route element={<Navigate replace to="/app/not-found" />} path="*" />
    </Routes>
  )
}

export const RagStudioApp = RagStudioRoutes

export function App({
  authGateway,
  localeRuntime,
  healthGateway,
  workspaceGateway,
}: {
  readonly authGateway?: AuthGateway | undefined
  readonly localeRuntime?: LocaleRuntime | undefined
  readonly healthGateway?: HealthGateway | undefined
  readonly workspaceGateway?: WorkspaceGateway | undefined
}): React.JSX.Element {
  const [runtime] = useState<LocaleRuntime>(() => localeRuntime ?? createBrowserLocaleRuntime())

  return (
    <LocaleProvider runtime={runtime}>
      <BrowserRouter>
        <RagStudioRoutes
          authGateway={authGateway}
          healthGateway={healthGateway}
          workspaceGateway={workspaceGateway}
        />
      </BrowserRouter>
    </LocaleProvider>
  )
}

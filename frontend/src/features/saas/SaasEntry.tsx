import { Building2, Plus } from "lucide-react"
import { useCallback, useEffect, useState } from "react"
import { useLocation, useNavigate } from "react-router-dom"

import { ApiError } from "../../api/errors"
import { Button } from "../../components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card"
import { Input } from "../../components/ui/input"
import { Label } from "../../components/ui/label"
import { AuthPage } from "./auth/AuthPage"
import { type AuthGateway, type AuthSession, createAuthGateway } from "./auth/auth-api"
import { ChatbotsPage } from "./chatbots/ChatbotsPage"
import type { AuthMode, AuthStatus, Credentials, SaasLocale } from "./model"
import { PeoplePage } from "./people/PeoplePage"
import { getSaasCopy } from "./saas-copy"
import { SaasShell } from "./shell/SaasShell"
import { SourcesPage } from "./sources/SourcesPage"
import { createTestChatGateway, createTestChatStreamGateway } from "./test-chat/test-chat-api"
import { InvitationAcceptancePage } from "./workspace-lifecycle/InvitationAcceptancePage"
import { WorkspaceLifecyclePanel } from "./workspace-lifecycle/WorkspaceLifecyclePanel"
import {
  createWorkspaceGateway,
  type WorkspaceGateway,
  type WorkspaceSummaryResponse,
} from "./workspaces/workspace-api"

type EntryState =
  | { readonly kind: "loading" }
  | { readonly kind: "authentication"; readonly status: AuthStatus }
  | {
      readonly kind: "workspace"
      readonly session: AuthSession
      readonly workspaces: readonly WorkspaceSummaryResponse[]
    }

const defaultAuthGateway = createAuthGateway()
const defaultWorkspaceGateway = createWorkspaceGateway()
const defaultTestChatGateway = createTestChatGateway()
const defaultTestChatStreamGateway = createTestChatStreamGateway()

export function SaasEntry({
  authGateway = defaultAuthGateway,
  locale,
  workspaceGateway = defaultWorkspaceGateway,
}: {
  readonly authGateway?: AuthGateway
  readonly locale: SaasLocale
  readonly workspaceGateway?: WorkspaceGateway
}): React.JSX.Element {
  const copy = getSaasCopy(locale)
  const location = useLocation()
  const navigate = useNavigate()
  const [mode, setMode] = useState<AuthMode>("sign-in")
  const [state, setState] = useState<EntryState>({ kind: "loading" })
  const [workspaceName, setWorkspaceName] = useState("")

  const selectAvailableWorkspace = useCallback(
    async (
      session: AuthSession,
      workspaces: readonly WorkspaceSummaryResponse[],
    ): Promise<AuthSession> => {
      if (session.workspace !== null) return session
      const firstWorkspace = workspaces[0]
      if (firstWorkspace === undefined) return session
      return authGateway.selectWorkspace(firstWorkspace.id)
    },
    [authGateway],
  )

  useEffect(() => {
    let active = true
    void authGateway
      .getSession()
      .then(async (session) => {
        const workspaces = await workspaceGateway.list()
        return { session: await selectAvailableWorkspace(session, workspaces), workspaces }
      })
      .then(({ session, workspaces }) => {
        if (active) setState({ kind: "workspace", session, workspaces })
      })
      .catch((error: unknown) => {
        if (!active) return
        if (error instanceof ApiError) {
          setState({ kind: "authentication", status: { kind: "ready" } })
          return
        }
        throw error
      })
    return (): void => {
      active = false
    }
  }, [authGateway, selectAvailableWorkspace, workspaceGateway])

  const authenticate = async (credentials: Credentials): Promise<void> => {
    setState({ kind: "authentication", status: { kind: "pending" } })
    try {
      let session: AuthSession
      if (mode === "sign-in") {
        session = await authGateway.signIn(credentials)
      } else {
        const outcome = await authGateway.signUp(credentials)
        if (outcome.confirmation_required) {
          setState({ kind: "authentication", status: { kind: "confirmation-required" } })
          return
        }
        session = await authGateway.getSession()
      }
      const workspaces = await workspaceGateway.list()
      setState({
        kind: "workspace",
        session: await selectAvailableWorkspace(session, workspaces),
        workspaces,
      })
    } catch (error) {
      if (error instanceof Error) {
        setState({ kind: "authentication", status: { kind: "error", message: copy.authError } })
        return
      }
      throw error
    }
  }

  const createWorkspace = async (event: React.FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault()
    if (state.kind !== "workspace") return
    const workspace = await workspaceGateway.create(workspaceName.trim())
    const session = await authGateway.selectWorkspace(workspace.id)
    setState({ kind: "workspace", session, workspaces: [...state.workspaces, workspace] })
  }

  if (state.kind === "loading") {
    return (
      <main className="rs-saas-loading" aria-busy="true">
        <span className="rs-saas-loading__mark" aria-hidden="true" />
        <p>{copy.submitting}</p>
      </main>
    )
  }

  if (state.kind === "authentication") {
    return (
      <AuthPage
        locale={locale}
        mode={mode}
        onAuthenticate={authenticate}
        onModeChange={setMode}
        status={state.status}
      />
    )
  }

  const activeWorkspace = state.session.workspace
  const invitationToken = new URLSearchParams(location.search).get("token") ?? ""

  if (location.pathname === "/saas/invitations/accept") {
    return (
      <InvitationAcceptancePage
        initialToken={invitationToken}
        locale={locale}
        onAccepted={async (workspace) => {
          const session = await authGateway.selectWorkspace(workspace.id)
          const workspaces = state.workspaces.some(({ id }) => id === workspace.id)
            ? state.workspaces
            : [...state.workspaces, workspace]
          setState({ kind: "workspace", session, workspaces })
          navigate(`/saas/workspaces/${encodeURIComponent(workspace.id)}/chatbots`, {
            replace: true,
          })
        }}
      />
    )
  }

  if (activeWorkspace === null) {
    return (
      <main className="rs-saas-start">
        <Card className="rs-saas-start__card">
          <CardHeader>
            <span className="rs-saas-auth__icon" aria-hidden="true">
              <Building2 size={20} />
            </span>
            <CardTitle>{copy.startWorkspace}</CardTitle>
          </CardHeader>
          <CardContent>
            <form className="rs-saas-form" onSubmit={(event) => void createWorkspace(event)}>
              <div className="rs-saas-field">
                <Label htmlFor="workspace-name">{copy.workspaceName}</Label>
                <Input
                  id="workspace-name"
                  maxLength={120}
                  minLength={1}
                  onChange={(event) => setWorkspaceName(event.currentTarget.value)}
                  required
                  value={workspaceName}
                />
              </div>
              <Button disabled={workspaceName.trim() === ""} type="submit">
                <Plus aria-hidden="true" size={17} />
                {copy.createWorkspace}
              </Button>
            </form>
          </CardContent>
        </Card>
      </main>
    )
  }

  return (
    <SaasShell
      activeWorkspaceId={activeWorkspace.id}
      email={state.session.email}
      locale={locale}
      onSelectWorkspace={async (workspaceId) => {
        const session = await authGateway.selectWorkspace(workspaceId)
        setState({ ...state, session })
      }}
      onSignOut={async () => {
        await authGateway.signOut()
        setState({ kind: "authentication", status: { kind: "ready" } })
      }}
      workspaceRole={activeWorkspace.role}
      workspaces={state.workspaces}
    >
      {location.pathname.includes("/people") ? (
        <div className="rs-saas-workspace-management">
          <PeoplePage
            locale={locale}
            workspaceId={activeWorkspace.id}
            workspaceRole={activeWorkspace.role}
          />
          <WorkspaceLifecyclePanel
            locale={locale}
            onArchived={() => {
              setState((current) => {
                if (current.kind !== "workspace") return current
                return {
                  kind: "workspace",
                  session: { ...current.session, workspace: null },
                  workspaces: current.workspaces.filter(({ id }) => id !== activeWorkspace.id),
                }
              })
              navigate("/saas", { replace: true })
            }}
            onTransferred={() => {
              setState((current) => {
                if (current.kind !== "workspace" || current.session.workspace === null) {
                  return current
                }
                return {
                  ...current,
                  session: {
                    ...current.session,
                    workspace: { ...current.session.workspace, role: "admin" },
                  },
                }
              })
            }}
            workspaceId={activeWorkspace.id}
            workspaceName={
              state.workspaces.find(({ id }) => id === activeWorkspace.id)?.name ??
              copy.activeWorkspace
            }
            workspaceRole={activeWorkspace.role}
          />
        </div>
      ) : location.pathname.includes("/sources") ? (
        <SourcesPage
          locale={locale}
          workspaceId={activeWorkspace.id}
          workspaceRole={activeWorkspace.role}
        />
      ) : (
        <ChatbotsPage
          locale={locale}
          testChatGateway={defaultTestChatGateway}
          testChatStreamGateway={defaultTestChatStreamGateway}
          workspaceId={activeWorkspace.id}
          workspaceRole={activeWorkspace.role}
        />
      )}
    </SaasShell>
  )
}

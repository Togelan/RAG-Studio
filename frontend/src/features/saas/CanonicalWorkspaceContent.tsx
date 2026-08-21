import { Building2, Plus } from "lucide-react"
import { useState } from "react"
import { useLocation, useNavigate } from "react-router-dom"

import { type ContextState, ContextSwitcher } from "../../components/shell/context-switcher"
import { Button } from "../../components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card"
import { Input } from "../../components/ui/input"
import { Label } from "../../components/ui/label"
import { getShellCopy } from "../../i18n/shell-copy"
import type { AccountContextController } from "../account/account-context"
import type { WorkspaceGateway } from "../account/workspace-gateway"
import type { AuthSession } from "../auth/auth-gateway"
import { ChatPage } from "../chat/ChatPage"
import { type HealthGateway, HealthStatus } from "../health/health-status"
import { SettingsPage } from "../settings/SettingsPage"
import { WelcomePage } from "../welcome/WelcomePage"
import { CanonicalInvitation, NotFound, PermissionNotice } from "./canonical-entry-context"
import { ChatbotsPage } from "./chatbots/ChatbotsPage"
import type { SaasLocale } from "./model"
import { PeoplePage } from "./people/PeoplePage"
import { getSaasCopy } from "./saas-copy"
import { SourcesPage } from "./sources/SourcesPage"
import { createTestChatGateway, createTestChatStreamGateway } from "./test-chat/test-chat-api"
import { WorkspaceLifecyclePanel } from "./workspace-lifecycle/WorkspaceLifecyclePanel"

const defaultTestChatGateway = createTestChatGateway()
const defaultTestChatStreamGateway = createTestChatStreamGateway()

export function CanonicalWorkspaceContent({
  controller,
  context,
  healthGateway,
  locale,
  session,
  workspaceGateway,
}: {
  readonly controller: AccountContextController
  readonly context: ContextState
  readonly healthGateway?: HealthGateway | undefined
  readonly locale: SaasLocale
  readonly session: AuthSession
  readonly workspaceGateway: WorkspaceGateway
}): React.JSX.Element {
  const copy = getSaasCopy(locale)
  const location = useLocation()
  const navigate = useNavigate()
  const [workspaceName, setWorkspaceName] = useState("")
  const activeAccount = session.accounts.find((account) => account.id === session.active_account_id)
  const activeWorkspace = session.workspace
  const managesWorkspace = activeWorkspace?.role === "owner" || activeWorkspace?.role === "admin"

  const createWorkspace = async (event: React.FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault()
    if (activeAccount === undefined || workspaceName.trim() === "") return
    const workspace = await workspaceGateway.create(workspaceName.trim())
    await controller.select(activeAccount.id, workspace.id)
    navigate(`/app/workspaces/${encodeURIComponent(workspace.id)}/chatbots`, { replace: true })
  }

  if (location.pathname === "/" || location.pathname === "/app") {
    return (
      <>
        <section aria-label={getShellCopy(locale).context} className="rs-home-context">
          <ContextSwitcher context={context} idPrefix="home-context" locale={locale} />
          <HealthStatus gateway={healthGateway} />
        </section>
        <WelcomePage />
        {activeAccount !== undefined && activeWorkspace === null ? (
          <Card className="rs-saas-start__card">
            <CardHeader>
              <Building2 aria-hidden="true" size={20} />
              <CardTitle>{copy.startWorkspace}</CardTitle>
            </CardHeader>
            <CardContent>
              <form className="rs-saas-form" onSubmit={(event) => void createWorkspace(event)}>
                <Label htmlFor="workspace-name">{copy.workspaceName}</Label>
                <Input
                  id="workspace-name"
                  maxLength={120}
                  minLength={1}
                  onChange={(event) => setWorkspaceName(event.currentTarget.value)}
                  required
                  value={workspaceName}
                />
                <Button disabled={workspaceName.trim() === ""} type="submit">
                  <Plus aria-hidden="true" size={17} />
                  {copy.createWorkspace}
                </Button>
              </form>
            </CardContent>
          </Card>
        ) : null}
      </>
    )
  }
  if (location.pathname === "/app/chat") return <ChatPage />
  if (location.pathname === "/app/settings") return <SettingsPage />
  if (location.pathname === "/app/invitations/accept") {
    return <CanonicalInvitation controller={controller} locale={locale} />
  }
  if (location.pathname === "/app/not-found") return <NotFound locale={locale} />

  const route = /^\/app\/workspaces\/([^/]+)\/(people|sources|chatbots)(?:\/.*)?$/u.exec(
    location.pathname,
  )
  if (activeWorkspace === null || route === null || route[1] !== activeWorkspace.id) {
    return <NotFound locale={locale} />
  }
  const resource = route[2]
  if (resource === "people") {
    if (!managesWorkspace) return <PermissionNotice locale={locale} />
    return (
      <div className="rs-saas-workspace-management">
        <PeoplePage
          locale={locale}
          workspaceId={activeWorkspace.id}
          workspaceRole={activeWorkspace.role}
        />
        <WorkspaceLifecyclePanel
          locale={locale}
          onArchived={() => {
            void controller.refresh()
            navigate("/app", { replace: true })
          }}
          onTransferred={() => void controller.refresh()}
          workspaceId={activeWorkspace.id}
          workspaceName={activeWorkspace.name ?? copy.activeWorkspace}
          workspaceRole={activeWorkspace.role}
        />
      </div>
    )
  }
  if (resource === "sources") {
    return managesWorkspace ? (
      <SourcesPage
        locale={locale}
        workspaceId={activeWorkspace.id}
        workspaceRole={activeWorkspace.role}
      />
    ) : (
      <PermissionNotice locale={locale} />
    )
  }
  return (
    <ChatbotsPage
      locale={locale}
      testChatGateway={defaultTestChatGateway}
      testChatStreamGateway={defaultTestChatStreamGateway}
      workspaceId={activeWorkspace.id}
      workspaceRole={activeWorkspace.role}
    />
  )
}

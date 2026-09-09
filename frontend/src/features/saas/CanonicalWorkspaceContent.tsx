import { useLocation, useNavigate } from "react-router-dom"

import { type ContextState, ContextSwitcher } from "../../components/shell/context-switcher"
import { getShellCopy } from "../../i18n/shell-copy"
import type { AccountContextController } from "../account/account-context"
import type { WorkspaceGateway } from "../account/workspace-gateway"
import type { AuthSession } from "../auth/auth-gateway"
import { BillingPage } from "../billing/BillingPage"
import { ChatPage } from "../chat/ChatPage"
import { type HealthGateway, HealthStatus } from "../health/health-status"
import { PersonalKnowledgePage } from "../personal-lab/PersonalKnowledgePage"
import { PersonalLabHome } from "../personal-lab/PersonalLabHome"
import { WidgetPublicationPage } from "../publication/WidgetPublicationPage"
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
  const activeAccount = session.accounts.find((account) => account.id === session.active_account_id)
  const activeWorkspace = session.workspace
  const hasPersonalContext = activeAccount !== undefined && activeWorkspace === null
  const managesWorkspace = activeWorkspace?.role === "owner" || activeWorkspace?.role === "admin"

  if (location.pathname === "/" || location.pathname === "/app") {
    return (
      <>
        <section aria-label={getShellCopy(locale).context} className="rs-home-context">
          <ContextSwitcher context={context} idPrefix="home-context" locale={locale} />
          <HealthStatus gateway={healthGateway} />
        </section>
        {hasPersonalContext ? <PersonalLabHome /> : <WelcomePage />}
      </>
    )
  }
  if (location.pathname === "/app/knowledge") {
    return hasPersonalContext ? <PersonalKnowledgePage /> : <NotFound locale={locale} />
  }
  if (location.pathname === "/app/chat") {
    return hasPersonalContext ? <ChatPage /> : <NotFound locale={locale} />
  }
  if (location.pathname === "/app/settings") {
    return hasPersonalContext ? <SettingsPage /> : <NotFound locale={locale} />
  }
  if (location.pathname === "/app/billing") {
    return hasPersonalContext ? <BillingPage /> : <NotFound locale={locale} />
  }
  if (location.pathname === "/app/widget") {
    return hasPersonalContext ? <WidgetPublicationPage /> : <NotFound locale={locale} />
  }
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

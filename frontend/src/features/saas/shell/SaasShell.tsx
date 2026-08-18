import { Bot, Building2, FileText, LogOut, Menu, Sparkles, Users } from "lucide-react"
import { useState } from "react"
import { Link, useLocation } from "react-router-dom"

import { Button } from "../../../components/ui/button"
import { Drawer, DrawerContent, DrawerTitle, DrawerTrigger } from "../../../components/ui/drawer"
import { Select } from "../../../components/ui/select"
import type { SaasLocale, WorkspaceRole, WorkspaceSummary } from "../model"
import { getSaasCopy, roleLabel } from "../saas-copy"
import "../saas.css"

export function SaasShell({
  activeWorkspaceId,
  children,
  email,
  locale,
  onSelectWorkspace,
  onSignOut,
  workspaceRole,
  workspaces,
}: {
  readonly activeWorkspaceId: string
  readonly children: React.ReactNode
  readonly email: string
  readonly locale: SaasLocale
  readonly onSelectWorkspace: (workspaceId: string) => Promise<void>
  readonly onSignOut: () => Promise<void>
  readonly workspaceRole: WorkspaceRole
  readonly workspaces: readonly WorkspaceSummary[]
}): React.JSX.Element {
  const copy = getSaasCopy(locale)
  const location = useLocation()
  const [selectionPending, setSelectionPending] = useState(false)
  const [navigationOpen, setNavigationOpen] = useState(false)
  const workspaceRoot = `/saas/workspaces/${encodeURIComponent(activeWorkspaceId)}`
  const managesPeople = workspaceRole === "owner" || workspaceRole === "admin"

  const selectWorkspace = (event: React.ChangeEvent<HTMLSelectElement>): void => {
    setSelectionPending(true)
    void onSelectWorkspace(event.currentTarget.value).finally(() => setSelectionPending(false))
  }

  const navigationLinks = (onNavigate: () => void = () => undefined): React.JSX.Element => (
    <>
      <Link
        aria-current={location.pathname.includes("/chatbots") ? "page" : undefined}
        onClick={onNavigate}
        to={`${workspaceRoot}/chatbots`}
      >
        <Bot aria-hidden="true" size={18} />
        {copy.chatbots}
      </Link>
      {managesPeople ? (
        <Link
          aria-current={location.pathname.includes("/sources") ? "page" : undefined}
          onClick={onNavigate}
          to={`${workspaceRoot}/sources`}
        >
          <FileText aria-hidden="true" size={18} />
          {copy.sources}
        </Link>
      ) : null}
      {managesPeople ? (
        <Link
          aria-current={location.pathname.includes("/people") ? "page" : undefined}
          onClick={onNavigate}
          to={`${workspaceRoot}/people`}
        >
          <Users aria-hidden="true" size={18} />
          {copy.people}
        </Link>
      ) : null}
    </>
  )

  return (
    <Drawer onOpenChange={setNavigationOpen} open={navigationOpen}>
      <div className="rs-saas-shell">
        <header className="rs-saas-shell__bar">
          <Link className="rs-saas-brand" to="/saas">
            <Sparkles aria-hidden="true" size={21} />
            <span>RAG-Studio</span>
          </Link>
          <label className="rs-saas-workspace-select" htmlFor="saas-workspace-selector">
            <span className="rs-visually-hidden">{copy.activeWorkspace}</span>
            <Building2 aria-hidden="true" size={17} />
            <Select
              aria-label={copy.activeWorkspace}
              disabled={selectionPending}
              id="saas-workspace-selector"
              onChange={selectWorkspace}
              options={workspaces.map((workspace) => ({
                label: workspace.name,
                value: workspace.id,
              }))}
              value={activeWorkspaceId}
            />
          </label>
          <DrawerTrigger asChild>
            <Button
              aria-label={copy.navigation}
              className="rs-saas-shell__menu"
              size="icon"
              variant="secondary"
            >
              <Menu aria-hidden="true" size={18} />
            </Button>
          </DrawerTrigger>
          <nav
            aria-label={copy.productLabel}
            className="rs-saas-shell__nav rs-saas-shell__nav--desktop"
          >
            {navigationLinks()}
          </nav>
          <div className="rs-saas-account">
            <span className={`rs-saas-role rs-saas-role--${workspaceRole}`}>
              {roleLabel(locale, workspaceRole)}
            </span>
            <span className="rs-saas-account__email">{email}</span>
            <Button
              aria-label={copy.signOut}
              onClick={() => void onSignOut()}
              size="icon"
              variant="secondary"
            >
              <LogOut aria-hidden="true" size={18} />
            </Button>
          </div>
        </header>
        <main className="rs-saas-shell__body">{children}</main>
      </div>
      <DrawerContent className="rs-saas-shell__drawer">
        <DrawerTitle>{copy.navigation}</DrawerTitle>
        <nav aria-label={copy.productLabel} className="rs-saas-shell__drawer-nav">
          {navigationLinks(() => setNavigationOpen(false))}
        </nav>
      </DrawerContent>
    </Drawer>
  )
}

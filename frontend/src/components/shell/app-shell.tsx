import { LogOut, Menu, Sparkles, UserRound } from "lucide-react"
import { useState } from "react"
import { Link, useLocation } from "react-router-dom"

import { useLocaleContext } from "../../app/locale-provider"
import { getShellCopy } from "../../i18n/shell-copy"
import { Button } from "../ui/button"
import { Drawer, DrawerContent, DrawerTitle, DrawerTrigger } from "../ui/drawer"
import { NavigationLinks, pageFromPath, pagePath } from "./app-navigation"

export type { WorkspaceNavigationItem } from "./app-navigation"

import type { WorkspaceNavigationItem } from "./app-navigation"
import { type ContextState, ContextStateNotice, ContextSwitcher } from "./context-switcher"
import { LocaleMenu } from "./locale-menu"
import "./app-shell.css"

function selectedContext(context: ContextState | undefined) {
  if (context?.state !== "ready") return undefined
  return context.availableContexts.find((candidate) => candidate.id === context.selectedContextId)
}

export function AppShell({
  children,
  context,
  pageTitle,
  user,
  workspaceNavigation,
}: {
  readonly children: React.ReactNode
  readonly context?: ContextState | undefined
  readonly pageTitle?: string | undefined
  readonly user?:
    | { readonly identity: string; readonly onSignOut: () => void | Promise<void> }
    | undefined
  readonly workspaceNavigation?: readonly WorkspaceNavigationItem[] | undefined
}): React.JSX.Element {
  const { pathname } = useLocation()
  const { locale, setLocale, t } = useLocaleContext()
  const shellCopy = getShellCopy(locale)
  const page = pageFromPath(pathname)
  const shellPageTitle =
    pageTitle ??
    (page === "welcome"
      ? t("welcome_title")
      : page === "billing"
        ? t("billing_title")
        : page === "widget"
          ? t("publication_page_title")
          : undefined)
  const showPageHeader = shellPageTitle !== undefined
  const [menuOpen, setMenuOpen] = useState(false)
  const activeContext = selectedContext(context)
  const personalNavigation = activeContext?.kind === "personal"
  const activeContextLabel =
    activeContext?.kind === "personal" ? shellCopy.personalLab : activeContext?.name

  return (
    <div className={`rs-shell${page === "chat" ? " rs-shell--workspace" : ""}`}>
      <header className="rs-shell__header">
        <Link
          aria-label="RAG-Studio Home"
          className="rs-shell__brand"
          to={pagePath("welcome", pathname)}
        >
          <Sparkles aria-hidden="true" size={20} />
          <span>RAG-Studio</span>
        </Link>
        <nav aria-label={t("aria_main_nav")} className="rs-shell__desktop-nav">
          <NavigationLinks
            personalNavigation={personalNavigation}
            workspaceNavigation={workspaceNavigation}
          />
        </nav>
        <div className="rs-shell__tools">
          <LocaleMenu
            ariaLabel={t("aria_lang_selector")}
            locale={locale}
            onLocaleChange={setLocale}
            optionLabels={{ en: t("aria_english"), ru: t("aria_russian") }}
          />
          {user !== undefined ? (
            <details className="rs-shell__user-menu">
              <summary aria-label={`${shellCopy.signedInAs} ${user.identity}`}>
                <UserRound aria-hidden="true" size={18} />
              </summary>
              <div className="rs-shell__user-panel">
                <p>{shellCopy.signedInAs}</p>
                <strong>{user.identity}</strong>
                {context?.accountName !== undefined ? (
                  <>
                    <p>{shellCopy.account}</p>
                    <strong>{context.accountName}</strong>
                  </>
                ) : null}
                {activeContextLabel !== undefined ? (
                  <>
                    <p>{shellCopy.context}</p>
                    <strong>{activeContextLabel}</strong>
                  </>
                ) : null}
                <Button onClick={() => void user.onSignOut()} variant="secondary">
                  <LogOut aria-hidden="true" size={16} />
                  {shellCopy.signOut}
                </Button>
              </div>
            </details>
          ) : null}
          <Drawer onOpenChange={setMenuOpen} open={menuOpen}>
            <DrawerTrigger asChild>
              <Button
                aria-label={t("aria_toggle_menu")}
                className="rs-shell__menu"
                size="icon"
                variant="secondary"
              >
                <Menu aria-hidden="true" size={20} />
              </Button>
            </DrawerTrigger>
            <DrawerContent className="rs-shell__drawer">
              <DrawerTitle>{t("aria_mobile_nav")}</DrawerTitle>
              <nav aria-label={t("aria_mobile_nav")} className="rs-shell__drawer-nav">
                {context !== undefined ? (
                  <div data-testid="shell-drawer-context">
                    <ContextSwitcher
                      context={context}
                      idPrefix="shell-drawer-context"
                      locale={locale}
                    />
                  </div>
                ) : null}
                <NavigationLinks
                  onNavigate={() => setMenuOpen(false)}
                  personalNavigation={personalNavigation}
                  workspaceNavigation={workspaceNavigation}
                />
                {user !== undefined ? (
                  <div className="rs-shell__drawer-account">
                    <p>{shellCopy.signedInAs}</p>
                    <strong>{user.identity}</strong>
                    <Button
                      className="rs-shell__drawer-sign-out"
                      onClick={() => {
                        setMenuOpen(false)
                        void user.onSignOut()
                      }}
                      variant="secondary"
                    >
                      <LogOut aria-hidden="true" size={16} />
                      {shellCopy.signOut}
                    </Button>
                  </div>
                ) : null}
              </nav>
            </DrawerContent>
          </Drawer>
        </div>
      </header>
      <main className="rs-shell__main">
        {showPageHeader ? (
          <header className="rs-page__header">
            <p className="rs-page__eyebrow">RAG-Studio</p>
            <h1 id="page-title">{shellPageTitle}</h1>
          </header>
        ) : null}
        <section className="rs-page" aria-labelledby={showPageHeader ? "page-title" : undefined}>
          {context === undefined || context.state === "ready" ? (
            children
          ) : (
            <div className="rs-shell__context-recovery">
              <ContextStateNotice context={context} locale={locale} />
              {page === "welcome" ? (
                <ContextSwitcher context={context} idPrefix="home-context" locale={locale} />
              ) : null}
            </div>
          )}
        </section>
      </main>
      <nav aria-label={t("aria_mobile_nav")} className="rs-shell__bottom-nav">
        <NavigationLinks mobileBottom personalNavigation={personalNavigation} />
      </nav>
    </div>
  )
}

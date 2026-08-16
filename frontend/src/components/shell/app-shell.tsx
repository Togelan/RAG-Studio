import { Languages, Menu, PanelTop, Settings2, Sparkles } from "lucide-react"
import { useState } from "react"
import { Link, useLocation } from "react-router-dom"

import { useLocaleContext } from "../../app/locale-provider"
import { type HealthGateway, HealthStatus } from "../../features/health/health-status"
import { Button } from "../ui/button"
import { Drawer, DrawerContent, DrawerTitle, DrawerTrigger } from "../ui/drawer"
import "./app-shell.css"

type ShellPage = "welcome" | "settings" | "chat"

type NavigationItem = {
  readonly icon: typeof Sparkles
  readonly key: "nav_welcome" | "nav_settings" | "nav_chat"
  readonly page: ShellPage
}

const navigationItems = [
  { icon: Sparkles, key: "nav_welcome", page: "welcome" },
  { icon: Settings2, key: "nav_settings", page: "settings" },
  { icon: PanelTop, key: "nav_chat", page: "chat" },
] as const satisfies readonly NavigationItem[]

const pageTitleKeys = {
  chat: "chat_title",
  settings: "settings_title",
  welcome: "welcome_title",
} as const

function pagePath(page: ShellPage, pathname: string): string {
  const prefix = pathname === "/app" || pathname.startsWith("/app/") ? "/app" : ""
  switch (page) {
    case "welcome":
      return prefix || "/"
    case "settings":
      return `${prefix}/settings`
    case "chat":
      return `${prefix}/chat`
  }
}

function NavigationLinks({ onNavigate }: { readonly onNavigate?: () => void }): React.JSX.Element {
  const { pathname } = useLocation()
  const { t } = useLocaleContext()
  const activePage = pageFromPath(pathname)

  return (
    <>
      {navigationItems.map(({ icon: Icon, key, page }) => {
        const active = page === activePage
        return (
          <Link
            aria-current={active ? "page" : undefined}
            className={`rs-shell__nav-link${active ? " rs-shell__nav-link--active" : ""}`}
            key={page}
            onClick={onNavigate}
            to={pagePath(page, pathname)}
          >
            <Icon aria-hidden="true" size={18} />
            <span>{t(key)}</span>
          </Link>
        )
      })}
      <span aria-disabled="true" className="rs-shell__nav-link rs-shell__nav-link--disabled">
        <PanelTop aria-hidden="true" size={18} />
        <span>{t("nav_dashboard")}</span>
        <span className="rs-shell__coming-soon">{t("nav_coming_soon")}</span>
      </span>
    </>
  )
}

function pageFromPath(pathname: string): ShellPage {
  switch (pathname) {
    case "/":
    case "/app":
      return "welcome"
    case "/settings":
    case "/app/settings":
      return "settings"
    case "/chat":
    case "/app/chat":
      return "chat"
    default:
      return "welcome"
  }
}

export function AppShell({
  children,
  healthGateway,
}: {
  readonly children: React.ReactNode
  readonly healthGateway?: HealthGateway | undefined
}): React.JSX.Element {
  const { pathname } = useLocation()
  const { locale, setLocale, t } = useLocaleContext()
  const page = pageFromPath(pathname)
  const [menuOpen, setMenuOpen] = useState(false)

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
          <NavigationLinks />
        </nav>
        <div className="rs-shell__tools">
          <HealthStatus gateway={healthGateway} />
          <label className="rs-shell__locale" htmlFor="locale-select">
            <Languages aria-hidden="true" size={16} />
            <span className="rs-visually-hidden">{t("aria_lang_selector")}</span>
            <select
              aria-label={t("aria_lang_selector")}
              id="locale-select"
              onChange={(event) => void setLocale(event.target.value === "ru" ? "ru" : "en")}
              value={locale}
            >
              <option aria-label={t("aria_english")} value="en">
                EN
              </option>
              <option aria-label={t("aria_russian")} value="ru">
                RU
              </option>
            </select>
          </label>
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
                <NavigationLinks onNavigate={() => setMenuOpen(false)} />
              </nav>
            </DrawerContent>
          </Drawer>
        </div>
      </header>
      <main className="rs-shell__main">
        <header className="rs-page__header">
          <p className="rs-page__eyebrow">RAG-Studio</p>
          <h1 id="page-title">{t(pageTitleKeys[page])}</h1>
        </header>
        <section className="rs-page" aria-labelledby="page-title">
          {children}
        </section>
      </main>
      <nav aria-label={t("aria_mobile_nav")} className="rs-shell__bottom-nav">
        <NavigationLinks />
      </nav>
    </div>
  )
}

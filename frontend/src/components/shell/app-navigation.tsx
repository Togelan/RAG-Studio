import { BookOpenText, CreditCard, PanelTop, RadioTower, Settings2, Sparkles } from "lucide-react"
import { Link, useLocation } from "react-router-dom"

import { useLocaleContext } from "../../app/locale-provider"

type ShellPage = "welcome" | "knowledge" | "settings" | "chat" | "billing" | "widget"
export type ResolvedShellPage = ShellPage | "workspace" | "neutral"

type NavigationItem = {
  readonly icon: typeof Sparkles
  readonly key:
    | "nav_welcome"
    | "nav_knowledge"
    | "nav_settings"
    | "nav_chat"
    | "nav_billing"
    | "nav_widget"
  readonly page: ShellPage
}

export type WorkspaceNavigationItem = {
  readonly label: string
  readonly to: string
}

const homeNavigation = { icon: Sparkles, key: "nav_welcome", page: "welcome" } as const
const personalNavigationItems = [
  { icon: BookOpenText, key: "nav_knowledge", page: "knowledge" },
  { icon: Settings2, key: "nav_settings", page: "settings" },
  { icon: PanelTop, key: "nav_chat", page: "chat" },
  { icon: CreditCard, key: "nav_billing", page: "billing" },
  { icon: RadioTower, key: "nav_widget", page: "widget" },
] as const satisfies readonly NavigationItem[]

export function pagePath(page: ShellPage, pathname: string): string {
  const prefix = pathname === "/app" || pathname.startsWith("/app/") ? "/app" : ""
  switch (page) {
    case "welcome":
      return prefix || "/"
    case "knowledge":
      return `${prefix}/knowledge`
    case "settings":
      return `${prefix}/settings`
    case "chat":
      return `${prefix}/chat`
    case "billing":
      return `${prefix}/billing`
    case "widget":
      return `${prefix}/widget`
  }
}

export function NavigationLinks({
  mobileBottom = false,
  onNavigate,
  personalNavigation,
  workspaceNavigation = [],
}: {
  readonly mobileBottom?: boolean | undefined
  readonly onNavigate?: (() => void) | undefined
  readonly personalNavigation: boolean
  readonly workspaceNavigation?: readonly WorkspaceNavigationItem[] | undefined
}): React.JSX.Element {
  const { pathname } = useLocation()
  const { t } = useLocaleContext()
  const activePage = pageFromPath(pathname)
  const navigationItems = personalNavigation
    ? [homeNavigation, ...personalNavigationItems]
    : [homeNavigation]
  const visibleNavigationItems = mobileBottom
    ? navigationItems.filter(
        (item) => item.page !== "knowledge" && item.page !== "billing" && item.page !== "widget",
      )
    : navigationItems

  return (
    <>
      {visibleNavigationItems.map(({ icon: Icon, key, page }) => {
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
      {workspaceNavigation.map((item) => (
        <Link
          aria-current={pathname === item.to ? "page" : undefined}
          className={`rs-shell__nav-link${pathname === item.to ? " rs-shell__nav-link--active" : ""}`}
          key={item.to}
          onClick={onNavigate}
          to={item.to}
        >
          <PanelTop aria-hidden="true" size={18} />
          <span>{item.label}</span>
        </Link>
      ))}
    </>
  )
}

export function pageFromPath(pathname: string): ResolvedShellPage {
  switch (pathname) {
    case "/":
    case "/app":
      return "welcome"
    case "/settings":
    case "/app/settings":
      return "settings"
    case "/app/knowledge":
      return "knowledge"
    case "/chat":
    case "/app/chat":
      return "chat"
    case "/app/billing":
      return "billing"
    case "/app/widget":
      return "widget"
    case "/app/invitations/accept":
    case "/app/not-found":
      return "neutral"
    default:
      if (pathname.startsWith("/app/workspaces/")) return "workspace"
      return "neutral"
  }
}

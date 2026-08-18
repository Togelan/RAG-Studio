import { useState } from "react"
import { BrowserRouter, Route, Routes } from "react-router-dom"

import { createBrowserLocaleRuntime } from "./app/browser-locale-runtime"
import { LocaleProvider, useLocaleContext } from "./app/locale-provider"
import { AppShell } from "./components/shell/app-shell"
import { ChatPage } from "./features/chat/ChatPage"
import type { HealthGateway } from "./features/health/health-status"
import { SaasEntry } from "./features/saas/SaasEntry"
import { SettingsPage } from "./features/settings/SettingsPage"
import { WelcomePage } from "./features/welcome/WelcomePage"
import type { LocaleRuntime } from "./i18n/locale-runtime"

function RoutedPage({
  children,
  healthGateway,
}: {
  readonly children: React.ReactNode
  readonly healthGateway?: HealthGateway | undefined
}): React.JSX.Element {
  return <AppShell healthGateway={healthGateway}>{children}</AppShell>
}

function SaasRoute(): React.JSX.Element {
  const { locale } = useLocaleContext()
  return <SaasEntry locale={locale} />
}

export function RagStudioApp({
  healthGateway,
}: {
  readonly healthGateway?: HealthGateway | undefined
}): React.JSX.Element {
  return (
    <Routes>
      <Route element={<SaasRoute />} path="/saas/*" />
      <Route
        element={
          <RoutedPage healthGateway={healthGateway}>
            <WelcomePage />
          </RoutedPage>
        }
        path="/"
      />
      <Route
        element={
          <RoutedPage healthGateway={healthGateway}>
            <WelcomePage />
          </RoutedPage>
        }
        path="/app"
      />
      <Route
        element={
          <RoutedPage healthGateway={healthGateway}>
            <SettingsPage />
          </RoutedPage>
        }
        path="/settings"
      />
      <Route
        element={
          <RoutedPage healthGateway={healthGateway}>
            <SettingsPage />
          </RoutedPage>
        }
        path="/app/settings"
      />
      <Route
        element={
          <RoutedPage healthGateway={healthGateway}>
            <ChatPage />
          </RoutedPage>
        }
        path="/chat"
      />
      <Route
        element={
          <RoutedPage healthGateway={healthGateway}>
            <ChatPage />
          </RoutedPage>
        }
        path="/app/chat"
      />
      <Route
        element={
          <RoutedPage healthGateway={healthGateway}>
            <WelcomePage />
          </RoutedPage>
        }
        path="*"
      />
    </Routes>
  )
}

export function App({
  localeRuntime,
  healthGateway,
}: {
  readonly localeRuntime?: LocaleRuntime | undefined
  readonly healthGateway?: HealthGateway | undefined
}): React.JSX.Element {
  const [runtime] = useState<LocaleRuntime>(() => localeRuntime ?? createBrowserLocaleRuntime())

  return (
    <LocaleProvider runtime={runtime}>
      <BrowserRouter>
        <RagStudioApp healthGateway={healthGateway} />
      </BrowserRouter>
    </LocaleProvider>
  )
}

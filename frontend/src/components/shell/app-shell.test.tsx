import { cleanup, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { afterEach, describe, expect, it, vi } from "vitest"

import { RagStudioApp } from "../../App"
import { LocaleProvider } from "../../app/locale-provider"
import { AccountIdSchema, UserIdSchema } from "../../features/account/account-contracts"
import type { AuthGateway, AuthSession } from "../../features/auth/auth-gateway"
import type { HealthGateway } from "../../features/health/health-status"
import { localeKeys } from "../../i18n/locale-inventory"
import {
  createLocaleRuntime,
  createLocaleTranslations,
  type LocaleRuntime,
} from "../../i18n/locale-runtime"
import { AppShell } from "./app-shell"

function translations(prefix: string): ReadonlyMap<(typeof localeKeys)[number], string> {
  const parsed = createLocaleTranslations(localeFixtureValues(prefix))
  if (parsed === null) {
    throw new Error("test translations must be complete")
  }
  return parsed
}

function localeFixtureValues(prefix: string): Record<string, string> {
  return {
    ...Object.fromEntries(localeKeys.map((key) => [key, `${prefix} ${key}`])),
    chat_session_message_count: `${prefix} {count}`,
    chat_retry_after: `${prefix} {seconds}`,
    settings_upload_file_types_helper: `${prefix} {count}`,
    ingestion_batch_limit: `${prefix} {count}`,
    ingestion_delete_document_aria: `${prefix} {name}`,
    ingestion_delete_document_message: `${prefix} {name}`,
    ingestion_upload_file_progress: `${prefix} {name}`,
  }
}

function createRuntime(
  initialLocale: "en" | "ru" = "en",
  translationPrefix: string = initialLocale,
): LocaleRuntime {
  return createLocaleRuntime({
    gateway: {
      setLocale: async (locale) => ({
        locale,
        translations: localeFixtureValues(locale),
      }),
    },
    initialLocale,
    initialTranslations: translations(translationPrefix),
  })
}

const readyHealthGateway: HealthGateway = {
  getStatus: async () => ({ api_key_configured: true, status: "ready" }),
}

const shellAccountId = AccountIdSchema.parse("00000000-0000-4000-8000-000000000010")

const shellSession: AuthSession = {
  user_id: UserIdSchema.parse("00000000-0000-4000-8000-000000000001"),
  email: "shell@example.test",
  accounts: [
    {
      id: shellAccountId,
      label: "Studio",
      owner: null,
      status: "active",
      workspaces: [],
    },
  ],
  active_account_id: shellAccountId,
  workspace: null,
}

const shellAuthGateway: AuthGateway = {
  getSession: async () => shellSession,
  recover: async () => shellSession,
  refresh: async () => shellSession,
  selectContext: async () => shellSession,
  signIn: async () => shellSession,
  signOut: async () => undefined,
  signUp: async () => ({ confirmation_required: false }),
}

function renderShell(
  initialEntry: string,
  healthGateway: HealthGateway = readyHealthGateway,
): LocaleRuntime {
  const runtime = createRuntime()
  render(
    <LocaleProvider runtime={runtime}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <RagStudioApp authGateway={shellAuthGateway} healthGateway={healthGateway} />
      </MemoryRouter>
    </LocaleProvider>,
  )
  return runtime
}

afterEach(cleanup)

describe("Stage 2 AppShell", () => {
  it("keeps React aliases active and generates alias-aware internal links", async () => {
    renderShell("/app/settings")

    expect(await screen.findByText("en settings_workspace_eyebrow")).toBeVisible()
    expect(screen.queryByRole("heading", { name: "en settings_title" })).not.toBeInTheDocument()
    expect(screen.getAllByRole("link", { name: "en nav_settings" })[0]).toHaveAttribute(
      "aria-current",
      "page",
    )
    expect(screen.getAllByRole("link", { name: "en nav_welcome" })[0]).toHaveAttribute(
      "href",
      "/app",
    )
    expect(screen.getAllByRole("link", { name: "en nav_chat" })[0]).toHaveAttribute(
      "href",
      "/app/chat",
    )
    expect(screen.queryByRole("link", { name: /Dashboard/iu })).not.toBeInTheDocument()
    expect(screen.queryByText("en nav_dashboard")).not.toBeInTheDocument()
    expect(screen.queryByText("en nav_coming_soon")).not.toBeInTheDocument()
  })

  it("assigns the wide workspace layout only to Chat routes", async () => {
    renderShell("/chat")

    expect(await screen.findByRole("region", { name: "en nav_chat" })).toBeVisible()
    expect(screen.queryByRole("heading", { name: "en chat_title" })).not.toBeInTheDocument()
    expect(document.querySelector(".rs-shell")).toHaveClass("rs-shell--workspace")

    cleanup()
    renderShell("/settings")

    expect(await screen.findByText("en settings_workspace_eyebrow")).toBeVisible()
    expect(document.querySelector(".rs-shell")).not.toHaveClass("rs-shell--workspace")
  })

  it("gives a canonical workspace route one contextual heading and active navigation item", () => {
    const runtime = createRuntime()
    render(
      <LocaleProvider runtime={runtime}>
        <MemoryRouter initialEntries={["/app/workspaces/workspace-a/chatbots"]}>
          <AppShell
            workspaceNavigation={[
              { label: "Chatbots", to: "/app/workspaces/workspace-a/chatbots" },
              { label: "Sources", to: "/app/workspaces/workspace-a/sources" },
            ]}
          >
            <h1>Chatbots</h1>
          </AppShell>
        </MemoryRouter>
      </LocaleProvider>,
    )

    expect(screen.getByRole("heading", { name: "Chatbots" })).toBeVisible()
    expect(screen.getAllByRole("heading")).toHaveLength(1)
    expect(screen.getAllByRole("link", { current: "page" })).toHaveLength(1)
    expect(screen.getByRole("link", { current: "page" })).toHaveTextContent("Chatbots")
    expect(screen.getAllByRole("link", { name: "en nav_welcome" })[0]).not.toHaveAttribute(
      "aria-current",
    )
    expect(screen.getAllByRole("link", { name: "en nav_chat" })[0]).not.toHaveAttribute(
      "aria-current",
    )
  })

  it("keeps Workspace selection out of the header and available in the drawer", async () => {
    const user = userEvent.setup()
    const runtime = createRuntime()
    render(
      <LocaleProvider runtime={runtime}>
        <MemoryRouter initialEntries={["/app/workspaces/workspace-a/chatbots"]}>
          <AppShell
            context={{
              accountName: "Northstar Account",
              availableContexts: [
                { id: "personal", kind: "personal" },
                { id: "workspace-a", kind: "workspace", name: "Research", role: "owner" },
              ],
              selectedContextId: "workspace-a",
              state: "ready",
            }}
            user={{ identity: "person@example.test", onSignOut: () => undefined }}
            workspaceNavigation={[
              { label: "Chatbots", to: "/app/workspaces/workspace-a/chatbots" },
            ]}
          >
            <h1>Chatbots</h1>
          </AppShell>
        </MemoryRouter>
      </LocaleProvider>,
    )

    expect(screen.queryByTestId("shell-header-context")).not.toBeInTheDocument()
    expect(screen.getByLabelText("Signed in as person@example.test")).toBeVisible()

    await user.click(screen.getByRole("button", { name: "en aria_toggle_menu" }))
    expect(
      within(screen.getByTestId("shell-drawer-context")).getByLabelText("Context"),
    ).toHaveValue("workspace-a")
  })

  it.each([
    ["/app/invitations/accept", "Accept invitation"],
    ["/app/not-found", "Unavailable route"],
  ])(
    "leaves the neutral %s route without a false shell heading or active navigation",
    (path, title) => {
      const runtime = createRuntime()
      render(
        <LocaleProvider runtime={runtime}>
          <MemoryRouter initialEntries={[path]}>
            <AppShell>
              <h1>{title}</h1>
            </AppShell>
          </MemoryRouter>
        </LocaleProvider>,
      )

      expect(screen.getByRole("heading", { level: 1, name: title })).toBeVisible()
      expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1)
      expect(screen.queryAllByRole("link", { current: "page" })).toHaveLength(0)
    },
  )

  it("switches the shell locale without a page reload and persists the active translation state", async () => {
    const user = userEvent.setup()
    const runtime = renderShell("/app")

    await screen.findByRole("heading", { name: "en welcome_title" })
    await user.click(screen.getByLabelText("en aria_lang_selector"))
    await user.click(screen.getByRole("button", { name: "en aria_russian" }))

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "ru welcome_title" })).toBeVisible(),
    )
    expect(runtime.getState().locale).toBe("ru")
    expect(document.documentElement).toHaveAttribute("lang", "ru")
    expect(screen.queryByText("ru nav_dashboard")).not.toBeInTheDocument()
    expect(screen.queryByText("ru nav_coming_soon")).not.toBeInTheDocument()
  })

  it("renders the authoritative initial Russian locale without a mount request", async () => {
    const runtime = createRuntime("ru")
    render(
      <LocaleProvider runtime={runtime}>
        <MemoryRouter initialEntries={["/app"]}>
          <RagStudioApp authGateway={shellAuthGateway} healthGateway={readyHealthGateway} />
        </MemoryRouter>
      </LocaleProvider>,
    )

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "ru welcome_title" })).toBeVisible(),
    )
    expect(document.documentElement).toHaveAttribute("lang", "ru")
  })

  it("opens the compact navigation with the keyboard and returns focus after Escape", async () => {
    const user = userEvent.setup()
    renderShell("/")

    const trigger = await screen.findByRole("button", { name: "en aria_toggle_menu" })
    await user.click(trigger)
    expect(screen.getByRole("dialog", { name: "en aria_mobile_nav" })).toBeVisible()
    await user.keyboard("{Escape}")
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it("exposes sign out in the opened compact navigation", async () => {
    const user = userEvent.setup()
    const onSignOut = vi.fn()
    const runtime = createRuntime()
    render(
      <LocaleProvider runtime={runtime}>
        <MemoryRouter initialEntries={["/app/chat"]}>
          <AppShell user={{ identity: "person@example.test", onSignOut }}>
            <p>Chat content</p>
          </AppShell>
        </MemoryRouter>
      </LocaleProvider>,
    )

    await user.click(await screen.findByRole("button", { name: "en aria_toggle_menu" }))

    const drawer = screen.getByRole("dialog", { name: "en aria_mobile_nav" })
    const signOut = within(drawer).getByRole("button", { name: "Sign out" })
    expect(signOut).toBeVisible()
    await user.click(signOut)
    expect(onSignOut).toHaveBeenCalledOnce()
  })

  it("keeps a long signed-in identity accessible and available in the opened user menu", async () => {
    const identity = "stage2-parity@redacted.invalid"
    const user = userEvent.setup()
    const runtime = createRuntime()
    render(
      <LocaleProvider runtime={runtime}>
        <MemoryRouter initialEntries={["/app"]}>
          <AppShell user={{ identity, onSignOut: () => undefined }}>
            <p>Content</p>
          </AppShell>
        </MemoryRouter>
      </LocaleProvider>,
    )

    expect(screen.getByLabelText(`Signed in as ${identity}`)).toBeVisible()
    await user.click(screen.getByLabelText(`Signed in as ${identity}`))
    expect(screen.getByRole("button", { name: "Sign out" })).toBeVisible()
    expect(screen.getAllByText(identity).at(-1)).toBeVisible()
  })

  it("clears previous child content before a revoked context can render", () => {
    const runtime = createRuntime()
    const { rerender } = render(
      <LocaleProvider runtime={runtime}>
        <MemoryRouter initialEntries={["/app"]}>
          <AppShell
            context={{
              accountName: "Northstar",
              availableContexts: [
                { id: "workspace-a", kind: "workspace", name: "Confidential", role: "owner" },
              ],
              selectedContextId: "workspace-a",
              state: "ready",
            }}
            user={{ identity: "person@example.test", onSignOut: () => undefined }}
          >
            <p>Workspace child content</p>
          </AppShell>
        </MemoryRouter>
      </LocaleProvider>,
    )
    expect(screen.getByText("Workspace child content")).toBeVisible()
    expect(screen.getByLabelText("Signed in as person@example.test")).toBeVisible()

    rerender(
      <LocaleProvider runtime={runtime}>
        <MemoryRouter initialEntries={["/app"]}>
          <AppShell context={{ accountName: "Northstar", state: "revoked" }}>
            <p>Workspace child content</p>
          </AppShell>
        </MemoryRouter>
      </LocaleProvider>,
    )

    expect(screen.queryByText("Workspace child content")).not.toBeInTheDocument()
    expect(screen.queryByText("Confidential")).not.toBeInTheDocument()
    expect(screen.getAllByRole("status").at(-1)).toHaveTextContent("no longer available")
  })

  it("keeps children cleared while an injected revoked-context recovery selection is made", async () => {
    const user = userEvent.setup()
    const runtime = createRuntime("ru")
    const onSelectContext = vi.fn()
    render(
      <LocaleProvider runtime={runtime}>
        <MemoryRouter initialEntries={["/app"]}>
          <AppShell
            context={{
              accountName: "Northstar",
              availableContexts: [{ id: "personal", kind: "personal" }],
              onSelectContext,
              state: "revoked",
            }}
          >
            <p>Stale workspace child</p>
          </AppShell>
        </MemoryRouter>
      </LocaleProvider>,
    )

    expect(screen.queryByText("Stale workspace child")).not.toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "ru aria_toggle_menu" }))
    await user.selectOptions(
      within(screen.getByRole("dialog")).getByLabelText("Выберите доступный контекст"),
      "personal",
    )
    expect(onSelectContext).toHaveBeenCalledWith("personal")
    expect(screen.queryByText("Stale workspace child")).not.toBeInTheDocument()
  })
})

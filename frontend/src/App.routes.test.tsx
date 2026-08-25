import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, useLocation } from "react-router-dom"
import { afterEach, describe, expect, it, vi } from "vitest"
import { RagStudioRoutes } from "./App"
import { requiresCsrfProof } from "./api/csrf"
import { ApiError } from "./api/errors"
import { LocaleProvider } from "./app/locale-provider"
import {
  AccountIdSchema,
  UserIdSchema,
  WorkspaceIdSchema,
} from "./features/account/account-contracts"
import type { WorkspaceGateway } from "./features/account/workspace-gateway"
import type { AuthGateway, AuthSession } from "./features/auth/auth-gateway"
import { localeKeys } from "./i18n/locale-inventory"
import { createLocaleRuntime, createLocaleTranslations } from "./i18n/locale-runtime"

const accountId = AccountIdSchema.parse("00000000-0000-4000-8000-000000000010")
const workspaceId = WorkspaceIdSchema.parse("00000000-0000-4000-8000-000000000011")

function authenticatedSession(): AuthSession {
  return {
    user_id: UserIdSchema.parse("00000000-0000-4000-8000-000000000001"),
    email: "member@example.test",
    accounts: [
      {
        id: accountId,
        label: "Department",
        owner: null,
        status: "active",
        workspaces: [{ id: workspaceId, name: "Support", role: "member" }],
      },
    ],
    active_account_id: accountId,
    workspace: { id: workspaceId, name: "Support", role: "member" },
  }
}

function personalSession(): AuthSession {
  return {
    ...authenticatedSession(),
    workspace: null,
  }
}

function gateway(session: AuthSession | null): AuthGateway {
  const recover =
    session === null
      ? vi.fn(() => Promise.reject(new ApiError(401, "The request could not be completed.", null)))
      : vi.fn(() => Promise.resolve(session))
  return {
    getSession: recover,
    recover,
    refresh: recover,
    selectContext: vi.fn(() => Promise.resolve(authenticatedSession())),
    signIn: vi.fn(() => Promise.resolve(authenticatedSession())),
    signOut: vi.fn(() => Promise.resolve()),
    signUp: vi.fn(() => Promise.resolve({ confirmation_required: false })),
  }
}

const workspaceGateway: WorkspaceGateway = {
  create: vi.fn(() =>
    Promise.resolve({ id: workspaceId, name: "Support", role: "member" as const }),
  ),
  list: vi.fn(() => Promise.resolve([])),
}

const retiredRouteMatrix = [
  ["/saas", "/app"],
  ["/saas/sign-in", "/app"],
  ["/saas/sign-up", "/app"],
  ["/saas/invitations/accept", "/app/invitations/accept"],
  [`/saas/workspaces/${workspaceId}/people`, `/app/workspaces/${workspaceId}/people`],
  [`/saas/workspaces/${workspaceId}/sources`, `/app/workspaces/${workspaceId}/sources`],
  [`/saas/workspaces/${workspaceId}/chatbots`, `/app/workspaces/${workspaceId}/chatbots`],
  [`/saas/workspaces/${workspaceId}/chatbots/new`, `/app/workspaces/${workspaceId}/chatbots`],
  [
    `/saas/workspaces/${workspaceId}/chatbots/00000000-0000-4000-8000-000000000012/edit`,
    `/app/workspaces/${workspaceId}/chatbots`,
  ],
  [
    `/saas/workspaces/${workspaceId}/chatbots/00000000-0000-4000-8000-000000000012/test`,
    `/app/workspaces/${workspaceId}/chatbots`,
  ],
  [
    `/saas/workspaces/${workspaceId}/chatbots/00000000-0000-4000-8000-000000000012/test?session=foreign`,
    `/app/workspaces/${workspaceId}/chatbots`,
  ],
  [
    `/saas/workspaces/${workspaceId}/sources?sort=private`,
    `/app/workspaces/${workspaceId}/sources`,
  ],
  [`/saas/workspaces/${workspaceId}/people?tab=members`, `/app/workspaces/${workspaceId}/people`],
  ["/saas/unknown/private", "/app/not-found"],
] as const

function LocationProbe(): React.JSX.Element {
  const location = useLocation()
  return <output data-testid="location">{JSON.stringify(location)}</output>
}

function renderRoute(path: string, authGateway: AuthGateway): void {
  const translations = createLocaleTranslations({
    ...Object.fromEntries(localeKeys.map((key) => [key, key])),
    chat_session_message_count: "Messages: {count}",
    chat_retry_after: "Retry in {seconds}",
    ingestion_batch_limit: "Files: {count}",
    ingestion_delete_document_aria: "Delete {name}",
    ingestion_delete_document_message: "Delete {name}",
    ingestion_upload_file_progress: "Upload {name}",
    nav_chat: "Chat",
    nav_knowledge: "Knowledge",
    nav_settings: "Settings",
    nav_welcome: "Home",
    settings_upload_file_types_helper: "Types: {count}",
  })
  if (translations === null) throw new Error("test translations must be complete")
  const localeRuntime = createLocaleRuntime({
    gateway: { setLocale: () => Promise.resolve({}) },
    initialLocale: "en",
    initialTranslations: translations,
  })
  render(
    <MemoryRouter initialEntries={[path]}>
      <LocaleProvider runtime={localeRuntime}>
        <RagStudioRoutes authGateway={authGateway} workspaceGateway={workspaceGateway} />
        <LocationProbe />
      </LocaleProvider>
    </MemoryRouter>,
  )
}

afterEach(cleanup)

describe("canonical RAG-Studio routes", () => {
  it("shows the Personal Lab journey only for a confirmed personal context", async () => {
    // Given: a signed-in identity with Personal Lab selected.
    renderRoute("/app/knowledge", gateway(personalSession()))

    // When: the protected deep link settles in the unified shell.
    const knowledge = await screen.findByRole("link", { name: "Knowledge" })

    // Then: all Personal destinations are real links and Knowledge is the sole location cue.
    expect(knowledge).toHaveAttribute("aria-current", "page")
    expect(screen.getByRole("link", { name: "Home" })).toHaveAttribute("href", "/app")
    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/app/settings")
    expect(screen.getByRole("link", { name: "Chat" })).toHaveAttribute("href", "/app/chat")
    expect(screen.queryByRole("heading", { level: 1, name: "Knowledge" })).toBeNull()
    expect(document.querySelectorAll(".rs-shell")).toHaveLength(1)
  })

  it("does not expose Personal destinations for a Workspace-only context", async () => {
    // Given: a signed-in identity with a server-confirmed Workspace selected.
    renderRoute(`/app/workspaces/${workspaceId}/chatbots`, gateway(authenticatedSession()))

    // When: the workspace route settles.
    await screen.findByRole("link", { name: "Chatbots" })

    // Then: Personal-only Knowledge, Settings, and Chat navigation stays absent.
    expect(screen.queryByRole("link", { name: "Knowledge" })).toBeNull()
    expect(screen.queryByRole("link", { name: "Settings" })).toBeNull()
    expect(screen.queryByRole("link", { name: "Chat" })).toBeNull()
  })

  it("requires CSRF proof for Personal mutations without changing public reads", () => {
    // Given: Personal and unrelated API paths.
    // When/Then: the Personal namespace joins the protected mutation boundary only.
    expect(requiresCsrfProof("/api/personal/knowledge/upload")).toBe(true)
    expect(requiresCsrfProof("/api/ui/locale")).toBe(false)
  })

  it.each(retiredRouteMatrix)("maps retired route %s to %s", async (retired, canonical) => {
    // Given: a signed-in user opens one documented retired route pattern.
    renderRoute(retired, gateway(authenticatedSession()))

    // When: the compatibility boundary translates the address.
    await waitFor(() =>
      expect(JSON.parse(screen.getByTestId("location").textContent ?? "{}").pathname).toBe(
        canonical,
      ),
    )

    // Then: unsupported query data is absent from the canonical address.
    expect(screen.getByTestId("location")).not.toHaveTextContent("private|foreign|tab=")
  })

  it.each(["/", "/sign-up", "/app/settings"])(
    "renders %s in a minimal public access surface when signed out",
    async (path) => {
      renderRoute(path, gateway(null))

      const expectedAction = path === "/sign-up" ? "Create account" : "Sign in"
      await screen.findByRole("button", { name: expectedAction })

      expect(screen.queryByRole("navigation", { name: "Main navigation" })).toBeNull()
      expect(screen.queryByRole("link", { name: "RAG-Studio Home" })).toBeNull()
      expect(screen.queryByRole("heading", { name: "Welcome to RAG Studio" })).toBeNull()
      expect(JSON.parse(screen.getByTestId("location").textContent ?? "{}").pathname).toBe(
        path === "/app/settings" ? "/sign-in" : path,
      )
    },
  )

  it("restores only the requested internal path after sign in", async () => {
    const auth = gateway(null)
    const user = userEvent.setup()
    renderRoute("/app/settings", auth)

    await user.type(await screen.findByLabelText("Email"), "member@example.test")
    await user.type(screen.getByLabelText("Password"), "correct-horse")
    await user.click(screen.getByRole("button", { name: "Sign in" }))

    await waitFor(() =>
      expect(JSON.parse(screen.getByTestId("location").textContent ?? "{}").pathname).toBe(
        "/app/settings",
      ),
    )
  })

  it("maps a retired workspace route to its canonical destination and drops unsupported query", async () => {
    // Given: a BFF-confirmed member context and a retired route with an unsupported filter.
    renderRoute(
      `/saas/workspaces/${workspaceId}/chatbots?status=private`,
      gateway(authenticatedSession()),
    )

    // When: compatibility routing settles.
    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent(
        `/app/workspaces/${workspaceId}/chatbots`,
      ),
    )

    // Then: the canonical AppShell owns navigation and no SaaS shell is mounted.
    expect(screen.getByRole("link", { name: "Chatbots" })).toHaveAttribute("aria-current", "page")
    expect(document.querySelector(".rs-saas-shell")).toBeNull()
  })

  it("moves an invitation bearer into one-time intake and removes it from the canonical URL", async () => {
    // Given: a signed-in user follows a retired invitation link containing a bearer.
    renderRoute("/saas/invitations/accept?token=one-time-secret", gateway(authenticatedSession()))

    // When: compatibility routing reaches the acceptance form.
    const tokenInput = await screen.findByLabelText("Invitation token")

    // Then: the value reaches the form once, while the address and rendered text do not retain it.
    expect(tokenInput).toHaveValue("one-time-secret")
    expect(JSON.parse(screen.getByTestId("location").textContent ?? "{}").pathname).toBe(
      "/app/invitations/accept",
    )
    await waitFor(() =>
      expect(screen.getByTestId("location")).not.toHaveTextContent("one-time-secret"),
    )
  })

  it("maps unknown and malformed retired deep links to sanitized recovery", async () => {
    // Given: an unknown route containing an untrusted identifier.
    renderRoute("/saas/workspaces/not-a-uuid/private/raw-value", gateway(authenticatedSession()))

    // When: the compatibility route is evaluated.
    await screen.findByRole("heading", { level: 1, name: "Page unavailable" })

    // Then: recovery stays in the sole shell and does not echo route data.
    expect(JSON.parse(screen.getByTestId("location").textContent ?? "{}").pathname).toBe(
      "/app/not-found",
    )
    expect(document.body).not.toHaveTextContent("not-a-uuid")
    expect(document.body).not.toHaveTextContent("raw-value")
  })

  it.each([
    ["/app/invitations/accept", "Accept invitation"],
    ["/app/not-found", "Page unavailable"],
  ])("renders neutral route %s with one truthful heading", async (path, heading) => {
    // Given: a confirmed session opens a neutral canonical route.
    renderRoute(path, gateway(authenticatedSession()))

    // When: the canonical content settles inside the shared shell.
    await screen.findByRole("heading", { level: 1, name: heading })

    // Then: no primary destination or false Welcome heading is active.
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1)
    expect(screen.queryByRole("heading", { level: 1, name: "Welcome to RAG Studio" })).toBeNull()
    expect(document.querySelectorAll(".rs-shell__desktop-nav [aria-current='page']")).toHaveLength(
      0,
    )
  })
})

import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ApiError } from "../../api/errors"
import { LocaleProvider } from "../../app/locale-provider"
import { localeKeys } from "../../i18n/locale-inventory"
import { createLocaleRuntime, createLocaleTranslations } from "../../i18n/locale-runtime"
import { AccountIdSchema, UserIdSchema, WorkspaceIdSchema } from "../account/account-contracts"
import type { WorkspaceGateway } from "../account/workspace-gateway"
import type { AuthGateway, AuthSession } from "../auth/auth-gateway"
import { SaasEntry } from "./SaasEntry"

const accountId = AccountIdSchema.parse("00000000-0000-4000-8000-000000000010")
const workspaceId = WorkspaceIdSchema.parse("00000000-0000-4000-8000-000000000011")

function session(active: boolean): AuthSession {
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
    active_account_id: active ? accountId : null,
    workspace: active ? { id: workspaceId, name: "Support", role: "member" } : null,
  }
}

function gateway(recovered: AuthSession | null): AuthGateway {
  const recover =
    recovered === null
      ? vi.fn(() => Promise.reject(new ApiError(401, "The request could not be completed.", null)))
      : vi.fn(() => Promise.resolve(recovered))
  return {
    getSession: recover,
    recover,
    refresh: recover,
    selectContext: vi.fn(() => Promise.resolve(session(true))),
    signIn: vi.fn(() => Promise.resolve(session(false))),
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

function renderEntry(path: string, authGateway: AuthGateway): void {
  const translations = createLocaleTranslations({
    ...Object.fromEntries(localeKeys.map((key) => [key, key])),
    chat_session_message_count: "Messages: {count}",
    chat_retry_after: "Retry in {seconds}",
    ingestion_batch_limit: "Files: {count}",
    ingestion_delete_document_aria: "Delete {name}",
    ingestion_delete_document_message: "Delete {name}",
    ingestion_upload_file_progress: "Upload {name}",
    settings_upload_file_types_helper: "Types: {count}",
  })
  if (translations === null) throw new Error("test translations must be complete")
  const runtime = createLocaleRuntime({
    gateway: { setLocale: () => Promise.resolve({}) },
    initialLocale: "en",
    initialTranslations: translations,
  })
  render(
    <MemoryRouter initialEntries={[path]}>
      <LocaleProvider runtime={runtime}>
        <SaasEntry authGateway={authGateway} locale="en" workspaceGateway={workspaceGateway} />
      </LocaleProvider>
    </MemoryRouter>,
  )
}

afterEach(cleanup)

describe("canonical RAG-Studio entry integration", () => {
  it("runs unauthenticated session recovery once across auth form rerenders", async () => {
    // Given: the BFF reports no recoverable session.
    const auth = gateway(null)
    const user = userEvent.setup()
    renderEntry("/app", auth)

    // When: the user changes the local authentication mode.
    await user.click(await screen.findByRole("button", { name: "Create account" }))

    // Then: the form rerender does not restart recovery.
    await waitFor(() => expect(auth.recover).toHaveBeenCalledOnce())
  })

  it("requires an explicit Account or Workspace choice instead of guessing the first", async () => {
    // Given: a session with one available Workspace and no confirmed active Account.
    const auth = gateway(session(false))
    const user = userEvent.setup()
    renderEntry("/app", auth)

    // When: the user explicitly selects the available Workspace context.
    await user.selectOptions(
      await screen.findByRole("combobox", { name: "Select an available context" }),
      `workspace:${accountId}:${workspaceId}`,
    )

    // Then: the typed Account and Workspace identifiers are sent to the BFF once.
    await waitFor(() =>
      expect(auth.selectContext).toHaveBeenCalledWith(accountId, workspaceId, expect.anything()),
    )
    expect(await screen.findByRole("link", { name: "Chatbots" })).toBeVisible()
  })

  it("shows a permission-honest recovery state for a member management deep link", async () => {
    // Given: a member has a confirmed Workspace but opens its Sources management route.
    renderEntry(`/app/workspaces/${workspaceId}/sources`, gateway(session(true)))

    // When: the confirmed context renders.
    await screen.findByText("Your confirmed role does not allow this task.")

    // Then: no source mutation control or retired SaaS shell is exposed.
    expect(screen.queryByText("Upload source")).not.toBeInTheDocument()
    expect(document.querySelector(".rs-saas-shell")).toBeNull()
  })

  it("recovers the BFF session after an auto-confirmed sign-up", async () => {
    // Given: sign-up succeeds without an email-confirmation step and establishes a BFF session.
    const recover = vi
      .fn()
      .mockRejectedValueOnce(new ApiError(401, "The request could not be completed.", null))
      .mockResolvedValueOnce(session(true))
    const auth: AuthGateway = {
      ...gateway(null),
      getSession: recover,
      recover,
      signUp: vi.fn(() => Promise.resolve({ confirmation_required: false })),
    }
    const user = userEvent.setup()
    renderEntry("/sign-up", auth)

    // When: the user completes the automatic-confirmation registration flow.
    await user.type(await screen.findByLabelText("Email"), "owner@example.test")
    await user.type(screen.getByLabelText("Password"), "correct-horse")
    await user.click(screen.getByRole("button", { name: "Create account" }))

    // Then: the recovered authenticated state reaches the application instead of a permanent busy screen.
    expect(await screen.findByRole("link", { name: "Chatbots" })).toBeVisible()
    expect(screen.queryByText("submitting")).not.toBeInTheDocument()
  })

  it("shows a generic sign-in error after a rejected credential request", async () => {
    // Given: session recovery is unauthenticated and the sign-in request receives a denial.
    const auth: AuthGateway = {
      ...gateway(null),
      signIn: vi.fn(() =>
        Promise.reject(new ApiError(401, "provider detail must not reach the user", null)),
      ),
    }
    const user = userEvent.setup()
    renderEntry("/sign-in", auth)

    // When: the user submits invalid credentials.
    await user.type(await screen.findByLabelText("Email"), "owner@example.test")
    await user.type(screen.getByLabelText("Password"), "incorrect-password")
    await user.click(screen.getByRole("button", { name: "Sign in" }))

    // Then: the UI clears context but presents only its stable generic recovery message.
    const alert = await screen.findByRole("alert")
    expect(alert).toHaveTextContent("Sign in could not be completed")
    expect(alert).not.toHaveTextContent("provider detail")
  })
})

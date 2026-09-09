import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ApiContractError, ApiError } from "../../api/errors"
import type { ChatGateway, ChatStreamGateway } from "../chat/model"
import type { PublicationGateway, PublicationProjection, WidgetState } from "./publication-api"
import { WidgetPublicationPage } from "./WidgetPublicationPage"

let locale: "en" | "ru" = "en"

vi.mock("../../app/locale-provider", () => ({
  useLocaleContext: () => ({ locale, t: (key: string) => key }),
}))

const enabled: PublicationProjection = {
  publication_id: "00000000-0000-4000-8000-000000000020",
  public_key: "00000000-0000-4000-8000-000000000021",
  allowed_origin: "https://widget.example.test",
  state: "enabled",
  key_version: 1,
  audit_event_count: 1,
}

function gateway(overrides: Partial<PublicationGateway> = {}): PublicationGateway {
  return {
    disable: vi.fn(() =>
      Promise.resolve({ ...enabled, state: "disabled" } satisfies PublicationProjection),
    ),
    load: vi.fn(() => Promise.resolve(enabled)),
    publish: vi.fn(() => Promise.resolve(enabled)),
    revoke: vi.fn(() =>
      Promise.resolve({
        ...enabled,
        state: "revoked",
        key_version: 2,
      } satisfies PublicationProjection),
    ),
    ...overrides,
  }
}

afterEach(() => {
  cleanup()
  locale = "en"
})

describe("WidgetPublicationPage", () => {
  it("offers a protected local preview without public publication controls", async () => {
    const chatGateway: ChatGateway = {
      cancel: vi.fn(() => Promise.resolve({ session_id: "session-1", status: "idle" as const })),
      clearMessages: vi.fn(() =>
        Promise.resolve({ session_id: "session-1", status: "cleared" as const }),
      ),
      commitMessage: vi.fn((_sessionId, input) =>
        Promise.resolve({
          content: input.content,
          created_at: "2026-08-26T12:00:00Z",
          id: input.message_id,
          role: "user" as const,
        }),
      ),
      createSession: vi.fn(() =>
        Promise.resolve({
          created_at: "2026-08-26T12:00:00Z",
          id: "session-1",
          message_count: 0,
          title: "Local preview",
        }),
      ),
      deleteSession: vi.fn(() =>
        Promise.resolve({ session_id: "session-1", status: "deleted" as const }),
      ),
      feedback: vi.fn(() =>
        Promise.resolve({ feedback: "positive" as const, status: "saved" as const }),
      ),
      listMessages: vi.fn(() => Promise.resolve([])),
      listSessions: vi.fn(() =>
        Promise.resolve([
          {
            created_at: "2026-08-26T12:00:00Z",
            id: "session-1",
            message_count: 0,
            title: "Local preview",
          },
        ]),
      ),
      renameSession: vi.fn(),
    }
    const streamGateway: ChatStreamGateway = {
      cancel: vi.fn(() => Promise.resolve({ session_id: "session-1", status: "stopped" as const })),
      reattach: vi.fn(() => Promise.resolve()),
      send: vi.fn(async (_input, options) => {
        options.onEvent({ type: "start" })
        options.onEvent({ type: "token", token: "Grounded answer" })
        options.onEvent({
          citations: [{ filename: "fixture.md", location: "characters 0-20" }],
          completed: true,
          full_response: "Grounded answer",
          message_id: "assistant-1",
          type: "end",
        })
      }),
    }
    const localDemo: WidgetState = {
      mode: "local_demo",
      protected_preview: true,
      public_publication: false,
    }
    const user = userEvent.setup()
    render(
      <WidgetPublicationPage
        chatGateway={chatGateway}
        chatStreamGateway={streamGateway}
        gateway={gateway({
          load: vi.fn(() => Promise.resolve(localDemo)),
        })}
      />,
    )

    expect(await screen.findByText("publication_local_preview_title")).toBeVisible()
    await waitFor(() => expect(chatGateway.listMessages).toHaveBeenCalledWith("session-1"))
    expect(streamGateway.reattach).not.toHaveBeenCalled()
    expect(screen.queryByLabelText("publication_origin_label")).toBeNull()
    expect(screen.queryByRole("button", { name: "publication_publish" })).toBeNull()
    expect(screen.queryByText("publication_snippet_label")).toBeNull()
    expect(document.body).not.toHaveTextContent("publication_description")

    await user.type(screen.getByLabelText("publication_local_preview_input"), "What is this?")
    await user.click(screen.getByRole("button", { name: "publication_local_preview_send" }))
    expect(await screen.findByText("Grounded answer")).toBeVisible()
    expect(screen.getByText(/fixture\.md/u)).toBeVisible()
  })

  it("renders an unpublished form without publishing automatically", async () => {
    const publicationGateway = gateway({
      load: vi.fn(() => Promise.reject(new ApiError(404, "sanitized", null))),
    })
    render(<WidgetPublicationPage gateway={publicationGateway} />)

    expect(await screen.findByLabelText("publication_origin_label")).toBeVisible()
    expect(screen.getByRole("button", { name: "publication_publish" })).toBeEnabled()
    expect(publicationGateway.publish).not.toHaveBeenCalled()
  })

  it.each(["", "*", "https://example.test/path"])(
    "blocks invalid origin %s with an accessible error and no request",
    async (origin) => {
      const user = userEvent.setup()
      const publicationGateway = gateway({
        load: vi.fn(() => Promise.reject(new ApiError(404, "sanitized", null))),
      })
      render(<WidgetPublicationPage gateway={publicationGateway} />)

      const input = await screen.findByLabelText("publication_origin_label")
      if (origin !== "") await user.type(input, origin)
      await user.click(screen.getByRole("button", { name: "publication_publish" }))

      expect(screen.getByRole("alert")).toHaveTextContent("publication_origin_invalid")
      expect(input).toHaveAttribute("aria-invalid", "true")
      expect(publicationGateway.publish).not.toHaveBeenCalled()
    },
  )

  it("publishes one canonical origin and renders the server projection", async () => {
    const user = userEvent.setup()
    const publish = vi.fn(() => Promise.resolve(enabled))
    render(
      <WidgetPublicationPage
        gateway={gateway({
          load: vi.fn(() => Promise.reject(new ApiError(404, "sanitized", null))),
          publish,
        })}
      />,
    )

    await user.type(
      await screen.findByLabelText("publication_origin_label"),
      enabled.allowed_origin,
    )
    await user.click(screen.getByRole("button", { name: "publication_publish" }))

    expect(await screen.findByText("publication_status_enabled")).toBeVisible()
    expect(screen.getByText(enabled.allowed_origin)).toBeVisible()
    expect(screen.getByText("500")).toBeVisible()
    expect(publish).toHaveBeenCalledOnce()
    expect(document.body).not.toHaveTextContent(enabled.publication_id)
  })

  it("renders a safe form-level error when the initial publish fails", async () => {
    const user = userEvent.setup()
    render(
      <WidgetPublicationPage
        gateway={gateway({
          load: vi.fn(() => Promise.reject(new ApiError(404, "sanitized", null))),
          publish: vi.fn(() => Promise.reject(new ApiError(503, "private detail", null))),
        })}
      />,
    )

    await user.type(
      await screen.findByLabelText("publication_origin_label"),
      enabled.allowed_origin,
    )
    await user.click(screen.getByRole("button", { name: "publication_publish" }))

    expect(await screen.findByRole("alert")).toHaveTextContent("publication_action_failed")
    expect(document.body).not.toHaveTextContent("private detail")
  })

  it("updates disable and terminal revoke states from server responses", async () => {
    const user = userEvent.setup()
    render(<WidgetPublicationPage gateway={gateway()} />)

    await user.click(await screen.findByRole("button", { name: "publication_disable" }))
    const disabledStatus = await screen.findByText("publication_status_disabled")
    expect(disabledStatus).toHaveFocus()

    await user.click(screen.getByRole("button", { name: "publication_revoke" }))
    expect(screen.getByRole("dialog")).toBeVisible()
    await user.keyboard("{Escape}")
    expect(screen.queryByRole("dialog")).toBeNull()
    expect(screen.getByRole("button", { name: "publication_revoke" })).toHaveFocus()
    await user.click(screen.getByRole("button", { name: "publication_revoke" }))
    await user.click(screen.getByRole("button", { name: "publication_revoke_confirm_action" }))
    const revokedStatus = await screen.findByText("publication_status_revoked")
    expect(revokedStatus).toHaveFocus()
    expect(screen.queryByRole("button", { name: "publication_disable" })).toBeNull()
  })

  it("copies a non-secret snippet containing only the public widget key", async () => {
    const user = userEvent.setup()
    let copiedText = ""
    const copyText = vi.fn((text: string) => {
      copiedText = text
      return Promise.resolve()
    })
    render(
      <WidgetPublicationPage
        applicationOrigin="https://rag-studio.example.test"
        copyText={copyText}
        gateway={gateway()}
      />,
    )

    await user.click(await screen.findByRole("button", { name: "publication_copy_snippet" }))

    expect(copiedText).toContain(`widget-key="${enabled.public_key}"`)
    expect(copiedText).toContain(
      'src="https://rag-studio.example.test/widget/rag-studio-widget.v1.js"',
    )
    expect(copiedText).toContain('api-base-url="https://rag-studio.example.test"')
    expect(copiedText).not.toContain(enabled.publication_id)
    expect(copiedText).not.toMatch(/secret|scope|collection|provider/iu)
    expect(await screen.findByText("publication_copied")).toBeVisible()
  })

  it.each([
    new ApiError(401, "private identifier", null),
    new ApiError(403, "private identifier", null),
    new ApiError(409, "private identifier", null),
    new ApiError(503, "private identifier", null),
    new ApiContractError(),
  ])("renders safe recovery for rejected or malformed data", async (error) => {
    render(
      <WidgetPublicationPage gateway={gateway({ load: vi.fn(() => Promise.reject(error)) })} />,
    )

    expect(await screen.findByRole("alert")).toHaveTextContent("publication_unavailable")
    expect(document.body).not.toHaveTextContent("private identifier")
    expect(screen.getByRole("button", { name: "publication_retry" })).toBeEnabled()
  })

  it("renders the same hierarchy and actions in Russian", async () => {
    locale = "ru"
    render(<WidgetPublicationPage gateway={gateway()} />)

    expect(await screen.findByText("publication_status_enabled")).toBeVisible()
    expect(screen.getByTestId("publication-locale")).toHaveAttribute("lang", "ru")
    expect(screen.getByRole("button", { name: "publication_copy_snippet" })).toBeEnabled()
  })
})

/// <reference types="node" />

import { readFileSync } from "node:fs"

import { cleanup, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"
import enLocale from "../../../../src/api/locales/en.json"
import ruLocale from "../../../../src/api/locales/ru.json"
import { ApiError } from "../../api/errors"
import { renderChat, CHAT_SESSION as SESSION } from "../../test/chat-page-support"
import type { SessionMutationResponse } from "./model"

const chatStyles = readFileSync("src/features/chat/chat-page.css", "utf8")

afterEach(cleanup)

describe("ChatPage", () => {
  it("drives the accessible composer, streamed answer, source fallback, copy, and feedback", async () => {
    const user = userEvent.setup()
    const writeText = vi.fn(async () => undefined)
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } })
    renderChat({
      cancel: vi.fn(
        async (): Promise<SessionMutationResponse> => ({
          session_id: SESSION.id,
          status: "stopped",
        }),
      ),
      reattach: vi.fn(async () => undefined),
      send: vi.fn(async (_input, options) => {
        options.onEvent({
          message_id: "assistant-a",
          protocol: "1",
          session_id: SESSION.id,
          type: "start",
        })
        options.onEvent({ stage: "retrieving", type: "progress" })
        options.onEvent({ token: "Answer", type: "token" })
        options.onEvent({
          citations: [{ content: "Relevant evidence excerpt.", filename: "guide.md", page: 3 }],
          completed: true,
          done: true,
          full_response: "Answer",
          message_id: "assistant-a",
          type: "done",
        })
      }),
    })

    await user.click(await screen.findByRole("button", { name: "Research" }))
    await user.type(screen.getByRole("textbox", { name: /message/iu }), "Question")
    await user.click(screen.getByRole("button", { name: /send/iu }))

    expect(await screen.findByText("Answer")).toBeVisible()
    expect(screen.getByText(/guide\.md/u)).toBeVisible()
    expect(screen.getByText(/Page 3/u)).toBeVisible()
    expect(screen.getByText("Source 1")).toBeVisible()
    const citationControl = screen.getByLabelText(/Inspect source 1/iu)
    const citation = citationControl.closest("details")
    expect(citation).not.toBeNull()
    await user.click(citationControl)
    expect(citation).toHaveAttribute("open")
    expect(screen.getByText("Relevant evidence excerpt.")).toBeVisible()
    expect(screen.getByRole("log")).toHaveAttribute("aria-live", "off")
    const copyButton = screen.getByRole("button", { name: /copy answer/iu })
    expect.soft(copyButton).toHaveClass("rs-chat__copy-answer")
    expect
      .soft(chatStyles)
      .toMatch(/\.rs-chat__copy-answer\.rs-button\s*\{\s*min-height:\s*var\(--rs-space-44\)/u)
    await user.click(copyButton)
    expect(writeText).toHaveBeenCalledWith("Answer")
    await user.click(screen.getByRole("button", { name: /^helpful$/iu }))
    expect(await screen.findByText(/Thanks/iu)).toBeVisible()
  })

  it("renders hostile message content as text and enforces the 10,000 character boundary", async () => {
    const user = userEvent.setup()
    const send = vi.fn(async () => undefined)
    renderChat({
      cancel: vi.fn(
        async (): Promise<SessionMutationResponse> => ({
          session_id: SESSION.id,
          status: "stopped",
        }),
      ),
      reattach: vi.fn(async () => undefined),
      send,
    })

    await user.click(await screen.findByRole("button", { name: "Research" }))
    const input = screen.getByRole("textbox", { name: /message/iu })
    await user.type(input, "<img src=x onerror=alert(1)>")
    await user.click(screen.getByRole("button", { name: /send/iu }))
    expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeVisible()
    expect(document.querySelector("img")).toBeNull()
    expect(input).toHaveAttribute("maxlength", "10000")
  })

  it("opens sessions in a modal drawer and returns focus after Escape", async () => {
    const user = userEvent.setup()
    renderChat({
      cancel: vi.fn(async () => ({ session_id: SESSION.id, status: "stopped" as const })),
      reattach: vi.fn(async () => undefined),
      send: vi.fn(async () => undefined),
    })

    const trigger = screen.getByRole("button", { name: enLocale.aria_toggle_sidebar })
    expect(screen.queryByRole("dialog", { name: /chat sessions/iu })).not.toBeInTheDocument()
    await user.click(trigger)

    const drawer = await screen.findByRole("dialog", { name: /chat sessions/iu })
    expect(within(drawer).getByRole("button", { name: "Research" })).toBeVisible()
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument()
    expect(within(drawer).getByRole("button", { name: /new chat/iu })).toHaveFocus()
    await user.keyboard("{Escape}")
    expect(screen.queryByRole("dialog", { name: /chat sessions/iu })).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it("keeps every direct child of the empty sessions list semantically valid", async () => {
    renderChat(
      {
        cancel: vi.fn(async () => ({ session_id: SESSION.id, status: "stopped" as const })),
        reattach: vi.fn(async () => undefined),
        send: vi.fn(async () => undefined),
      },
      "en",
      [],
    )

    const list = await screen.findByRole("list", { name: enLocale.aria_chat_sessions })
    expect(Array.from(list.children).map((child) => child.tagName)).toEqual(["LI"])
  })

  it("keeps the compact composer control at the mobile touch-target size", async () => {
    renderChat({
      cancel: vi.fn(async () => ({ session_id: SESSION.id, status: "stopped" as const })),
      reattach: vi.fn(async () => undefined),
      send: vi.fn(async () => undefined),
    })

    const input = await screen.findByRole("textbox", { name: /message/iu })
    expect(input).toHaveClass("rs-chat__composer-input")
    expect(screen.getByRole("button", { name: enLocale.aria_regenerate })).toHaveClass(
      "rs-chat__regenerate",
    )
    expect(chatStyles).toMatch(
      /@media \(max-width: 48rem\)[\s\S]*?\.rs-chat__messages\s*\{\s*min-height:\s*28dvh/u,
    )
    expect(chatStyles).toMatch(
      /@media \(max-width: 48rem\)[\s\S]*?\.rs-chat__empty\s*\{\s*margin:\s*var\(--rs-space-24\) auto/u,
    )
  })

  it("uses the navigation label without repeating a page heading", () => {
    renderChat({
      cancel: vi.fn(async () => ({ session_id: SESSION.id, status: "stopped" as const })),
      reattach: vi.fn(async () => undefined),
      send: vi.fn(async () => undefined),
    })

    expect(screen.queryByRole("heading", { level: 1 })).not.toBeInTheDocument()
    expect(
      screen.queryByRole("heading", { name: enLocale.chat_feature_title }),
    ).not.toBeInTheDocument()
    expect(document.querySelector(".rs-chat")).toHaveAttribute("aria-label", enLocale.nav_chat)
  })

  it("localizes retry timing and session message-count metadata in Russian", async () => {
    renderChat(
      {
        cancel: vi.fn(async () => ({ session_id: SESSION.id, status: "stopped" as const })),
        reattach: vi.fn(async () => {
          throw new ApiError(429, "Too many requests", 7)
        }),
        send: vi.fn(async () => undefined),
      },
      "ru",
    )

    expect(await screen.findByRole("alert")).toHaveTextContent(
      ruLocale.chat_retry_after.replace("{seconds}", "7"),
    )
    expect(
      screen.getByTitle(ruLocale.chat_session_message_count.replace("{count}", "0")),
    ).toBeVisible()
    expect(screen.queryByText(/Retry after/iu)).not.toBeInTheDocument()
  })

  it("localizes the backend default session title in Russian", async () => {
    renderChat(
      {
        cancel: vi.fn(async () => ({ session_id: SESSION.id, status: "stopped" as const })),
        reattach: vi.fn(async () => undefined),
        send: vi.fn(async () => undefined),
      },
      "ru",
      [{ ...SESSION, title: "New Session" }],
    )

    await screen.findByRole("button", { name: ruLocale.chat_new_chat })
    expect(screen.queryAllByText("New Session")).toHaveLength(0)
    expect(screen.getAllByText(ruLocale.chat_new_session).length).toBeGreaterThan(1)
  })

  it("uses authoritative Russian copy when session creation fails", async () => {
    const user = userEvent.setup()
    renderChat(
      {
        cancel: vi.fn(async () => ({ session_id: SESSION.id, status: "stopped" as const })),
        reattach: vi.fn(async () => undefined),
        send: vi.fn(async () => undefined),
      },
      "ru",
      [],
      vi.fn(async () => {
        throw new ApiError(405, "The request could not be completed. Please try again.", null)
      }),
    )

    const createButtons = await screen.findAllByRole("button", { name: ruLocale.chat_new_chat })
    const createButton = createButtons.shift()
    if (createButton === undefined) throw new Error("Expected a visible new-chat control")
    await user.click(createButton)

    const alert = await screen.findByRole("alert")
    expect(alert).toHaveTextContent(ruLocale.chat_stream_failed)
    expect(alert).not.toHaveTextContent("The request could not be completed")
  })
})

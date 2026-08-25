import { mkdir } from "node:fs/promises"
import { resolve } from "node:path"
import { expect, type Page, test } from "@playwright/test"
import { z } from "zod"

const accountId = "00000000-0000-4000-8000-000000000041"
const sessionId = "personal-session-a"
const MessageBodySchema = z.object({ content: z.string(), message_id: z.string() })
const SendBodySchema = z.object({ message_id: z.string() })
const FeedbackBodySchema = z.object({ feedback: z.string() })
const browserEvidenceRoot = resolve(
  "..",
  ".omo",
  "evidence",
  "group-2-personal-lab",
  "task-8",
  "browser",
)

type ChatMessage = {
  readonly citations: readonly Record<string, unknown>[]
  readonly content: string
  readonly created_at: string
  readonly generated_from: string | null
  readonly id: string
  readonly in_reply_to: string | null
  readonly role: "assistant" | "user"
}

async function mockPersonalSession(page: Page): Promise<void> {
  await page.route("**/api/saas/auth/session", (route) =>
    route.fulfill({
      contentType: "application/json",
      json: {
        accounts: [
          {
            id: accountId,
            label: "Private account",
            owner: null,
            status: "active",
            workspaces: [],
          },
        ],
        active_account_id: accountId,
        email: "personal-chat@redacted.invalid",
        user_id: "00000000-0000-4000-8000-000000000040",
        workspace: null,
      },
    }),
  )
  await page.route("**/api/saas/auth/csrf", (route) => route.fulfill({ status: 204 }))
  await page.route("**/health", (route) =>
    route.fulfill({ contentType: "application/json", json: { status: "ok" } }),
  )
}

test("Personal Chat streams cited answers, stops safely, and reloads scoped history", async ({
  page,
}, testInfo) => {
  await mkdir(browserEvidenceRoot, { recursive: true })
  await page.setViewportSize({ width: 1440, height: 900 })
  // Given: one authenticated Personal Lab with a scoped in-browser API fixture.
  const baseURL = testInfo.project.use.baseURL
  if (typeof baseURL !== "string") throw new Error("Playwright baseURL is required")
  await page
    .context()
    .addCookies([
      { name: "ragstudio-development-csrf", url: baseURL, value: "personal-chat-proof" },
    ])
  await mockPersonalSession(page)
  let sessionsExist = false
  let holdNextStream = true
  let feedbackValue: string | null = null
  const messages: ChatMessage[] = []
  await page.route("**/api/personal/chat/**", async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    const method = request.method()
    if (path.endsWith("/sessions") && method === "GET") {
      await route.fulfill({
        contentType: "application/json",
        json: sessionsExist
          ? [
              {
                created_at: "2026-08-23T00:00:00Z",
                id: sessionId,
                message_count: messages.length,
                title: "New Session",
              },
            ]
          : [],
      })
      return
    }
    if (path.endsWith("/sessions") && method === "POST") {
      sessionsExist = true
      await route.fulfill({
        contentType: "application/json",
        json: {
          created_at: "2026-08-23T00:00:00Z",
          id: sessionId,
          message_count: 0,
          title: "New Session",
        },
        status: 201,
      })
      return
    }
    if (path.endsWith(`/${sessionId}/messages`) && method === "GET") {
      await route.fulfill({ contentType: "application/json", json: messages })
      return
    }
    if (path.endsWith(`/${sessionId}/messages`) && method === "POST") {
      const body = MessageBodySchema.parse(request.postDataJSON())
      const message: ChatMessage = {
        citations: [],
        content: body.content,
        created_at: "2026-08-23T00:00:01Z",
        generated_from: null,
        id: body.message_id,
        in_reply_to: null,
        role: "user",
      }
      messages.push(message)
      await route.fulfill({ contentType: "application/json", json: message, status: 201 })
      return
    }
    if (path.endsWith("/send") && method === "POST") {
      const body = SendBodySchema.parse(request.postDataJSON())
      const heldStream = holdNextStream
      if (heldStream) {
        holdNextStream = false
        await new Promise((resolve) => setTimeout(resolve, 500))
      }
      const assistant: ChatMessage = {
        citations: [{ content: "Scoped evidence.", filename: "private.md", location: "Section 1" }],
        content: "Scoped answer",
        created_at: "2026-08-23T00:00:02Z",
        generated_from: "personal-lab",
        id: `assistant-${body.message_id}`,
        in_reply_to: body.message_id,
        role: "assistant",
      }
      if (!heldStream) messages.push(assistant)
      await route.fulfill({
        body: [
          `event: start\ndata: {"protocol":"1","session_id":"${sessionId}"}\n\n`,
          'event: progress\ndata: {"stage":"complete"}\n\n',
          `event: done\ndata: ${JSON.stringify({ citations: assistant.citations, completed: false, done: true, full_response: assistant.content, generated_from: assistant.generated_from, message_id: assistant.id })}\n\n`,
        ].join(""),
        contentType: "text/event-stream",
      })
      return
    }
    if (path.endsWith(`/${sessionId}/stream`) && method === "GET") {
      await route.fulfill({
        contentType: "application/json",
        json: { detail: "No active response." },
        status: 404,
      })
      return
    }
    if (path.endsWith(`/${sessionId}/cancel`) && method === "POST") {
      await route.fulfill({
        contentType: "application/json",
        json: { session_id: sessionId, status: "stopped" },
      })
      return
    }
    if (path.endsWith("/feedback") && method === "POST") {
      const body = FeedbackBodySchema.parse(request.postDataJSON())
      feedbackValue = body.feedback
      await route.fulfill({
        contentType: "application/json",
        json: { feedback: body.feedback, id: "feedback-a", status: "saved" },
        status: 201,
      })
      return
    }
    await route.fulfill({
      contentType: "application/json",
      json: { detail: "Not found" },
      status: 404,
    })
  })

  // When: the user creates a session, stops one request, then completes a cited answer.
  await page.goto("/app/chat?lang=en")
  await page.locator(".rs-chat__new:visible").click()
  const composer = page.getByRole("textbox", { name: /message/iu })
  await composer.fill("Stop this request")
  await page.getByRole("button", { name: /send/iu }).click()
  await page.getByRole("button", { name: /stop/iu }).click()
  await expect(page.getByText("Response stopped.")).toBeVisible()
  await composer.fill("Use my private source")
  await page.getByRole("button", { name: /send/iu }).click()

  // Then: citations and feedback are truthful, and reload recovers only scoped history.
  await expect(page.getByText("Scoped answer")).toBeVisible()
  await page.getByLabel(/Inspect source 1/iu).click()
  await expect(page.getByText("Scoped evidence.")).toBeVisible()
  await page.getByRole("button", { name: /^helpful$/iu }).click()
  await expect.poll(() => feedbackValue).toBe("like")
  await page.reload()
  await expect(page.getByText("Scoped answer")).toBeVisible()
  await expect(page.locator(".rs-chat__error")).toHaveCount(0)
  await page.screenshot({
    fullPage: true,
    path: resolve(browserEvidenceRoot, "personal-chat-1440.png"),
  })
  await page.setViewportSize({ width: 360, height: 800 })
  await expect(page.locator("body")).toHaveJSProperty("scrollWidth", 360)
  await page.screenshot({
    fullPage: true,
    path: resolve(browserEvidenceRoot, "personal-chat-360.png"),
  })
})

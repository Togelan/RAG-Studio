import { mkdir } from "node:fs/promises"
import { resolve } from "node:path"
import { expect, type Page, test } from "@playwright/test"

const CHAT_SESSION_KEY = "rag-studio-chat-session"
const evidenceRoot = resolve(
  "..",
  ".omo",
  "evidence",
  "group-2-personal-lab",
  "task-8",
  "stale-state",
)

type IdentityPhase = "first" | "signed-out" | "second"

function authSession(phase: Exclude<IdentityPhase, "signed-out">): Record<string, unknown> {
  const suffix = phase === "first" ? "1" : "2"
  return {
    accounts: [
      {
        id: `00000000-0000-4000-8000-00000000005${suffix}`,
        label: `Personal ${suffix}`,
        owner: null,
        status: "active",
        workspaces: [],
      },
    ],
    active_account_id: `00000000-0000-4000-8000-00000000005${suffix}`,
    email: `personal-${suffix}@redacted.invalid`,
    user_id: `00000000-0000-4000-8000-00000000006${suffix}`,
    workspace: null,
  }
}

function chatSession(phase: Exclude<IdentityPhase, "signed-out">): Record<string, unknown> {
  const second = phase === "second"
  return {
    created_at: "2026-08-23T00:00:00Z",
    id: second ? "personal-session-b" : "personal-session-a",
    message_count: 0,
    title: second ? "Second session" : "First session",
  }
}

async function mockSignOutJourney(
  page: Page,
  phase: { value: IdentityPhase },
  secondContextPaths: string[],
): Promise<void> {
  await page.route("**/api/saas/auth/session", (route) => {
    if (phase.value === "signed-out") return route.fulfill({ status: 401 })
    return route.fulfill({ contentType: "application/json", json: authSession(phase.value) })
  })
  await page.route("**/api/saas/auth/csrf", (route) => route.fulfill({ status: 204 }))
  await page.route("**/api/saas/auth/signout", (route) => {
    phase.value = "signed-out"
    return route.fulfill({ status: 204 })
  })
  await page.route("**/health", (route) =>
    route.fulfill({ contentType: "application/json", json: { status: "ok" } }),
  )
  await page.route("**/api/personal/chat/**", (route) => {
    const path = new URL(route.request().url()).pathname
    if (phase.value === "second") secondContextPaths.push(path)
    if (path.endsWith("/sessions")) {
      if (phase.value === "signed-out") return route.fulfill({ status: 401 })
      return route.fulfill({ contentType: "application/json", json: [chatSession(phase.value)] })
    }
    if (path.endsWith("/messages")) {
      return route.fulfill({ contentType: "application/json", json: [] })
    }
    return route.fulfill({
      contentType: "application/json",
      json: { detail: "Not found" },
      status: 404,
    })
  })
}

test("successful sign-out cannot restore a stale chat session in the next Personal context", async ({
  page,
}, testInfo) => {
  // Given: the first Personal context has remembered session A.
  const baseURL = testInfo.project.use.baseURL
  if (typeof baseURL !== "string") throw new Error("Playwright baseURL is required")
  const phase: { value: IdentityPhase } = { value: "first" }
  const secondContextPaths: string[] = []
  await mkdir(evidenceRoot, { recursive: true })
  await page
    .context()
    .addCookies([{ name: "ragstudio-development-csrf", url: baseURL, value: "signout-proof" }])
  await page.addInitScript(
    ({ key, value }) => {
      if (globalThis.sessionStorage.getItem("chat-session-seeded") !== "true") {
        globalThis.localStorage.setItem(key, value)
        globalThis.sessionStorage.setItem("chat-session-seeded", "true")
      }
    },
    { key: CHAT_SESSION_KEY, value: "personal-session-a" },
  )
  await mockSignOutJourney(page, phase, secondContextPaths)
  await page.goto("/app/chat?lang=en")
  await expect(page.getByText("First session").first()).toBeVisible()

  // When: AccountContext completes sign-out successfully.
  await page.locator(".rs-shell__user-menu summary").click()
  await page.getByRole("button", { name: /^sign out$/iu }).click()
  await expect(page).toHaveURL(/\/sign-in$/u)

  // Then: the key is absent before a second Personal context is recovered.
  await expect
    .poll(() => page.evaluate((key) => globalThis.localStorage.getItem(key), CHAT_SESSION_KEY))
    .toBeNull()
  phase.value = "second"
  await page.reload()
  await page.goto("/app/chat?lang=en")
  await expect(page.getByText("Second session").first()).toBeVisible()
  await expect
    .poll(() => page.evaluate((key) => globalThis.localStorage.getItem(key), CHAT_SESSION_KEY))
    .toBe("personal-session-b")
  expect(secondContextPaths.some((path) => path.includes("personal-session-a"))).toBe(false)
  await page.screenshot({
    fullPage: true,
    path: resolve(evidenceRoot, "second-personal-context.png"),
  })
})

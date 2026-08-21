import { mkdir } from "node:fs/promises"
import { resolve } from "node:path"
import { expect, type Page, test } from "@playwright/test"

const accountId = "00000000-0000-4000-8000-000000000010"
const workspaceId = "00000000-0000-4000-8000-000000000011"
const evidenceRoot = resolve(
  process.cwd(),
  "..",
  ".omo",
  "evidence",
  "group-1-unified-rag-studio-shell-auth",
  "task-9",
  "visual",
)

const session = {
  user_id: "00000000-0000-4000-8000-000000000001",
  email: "qa@redacted.invalid",
  accounts: [
    {
      id: accountId,
      label: "QA Account",
      owner: null,
      status: "active",
      workspaces: [{ id: workspaceId, name: "QA Workspace", role: "member" }],
    },
  ],
  active_account_id: accountId,
  workspace: { id: workspaceId, name: "QA Workspace", role: "member" },
}

async function mockAuthenticatedBff(page: Page): Promise<void> {
  await page.route("**/api/saas/auth/session", (route) =>
    route.fulfill({ contentType: "application/json", json: session }),
  )
  await page.route(`**/api/saas/workspaces/${workspaceId}/chatbots`, (route) =>
    route.fulfill({ contentType: "application/json", json: [] }),
  )
}

test.describe("Group 1 canonical route cutover", () => {
  test("retired deep links settle in the one canonical shell", async ({ page }) => {
    // Given: a server-confirmed Workspace member and retired deep links.
    await mockAuthenticatedBff(page)
    await mkdir(evidenceRoot, { recursive: true })

    // When: the member opens a retired chatbot route with unsupported query data.
    const retiredResponse = await page.goto(
      `/saas/workspaces/${workspaceId}/chatbots?status=private`,
    )

    // Then: the canonical address and sole RAG-Studio shell replace the SaaS surface.
    expect(retiredResponse?.status()).toBe(200)
    await expect(page).toHaveURL(`/app/workspaces/${workspaceId}/chatbots`)
    await expect(page.locator(".rs-shell")).toHaveCount(1)
    await expect(page.locator(".rs-saas-shell")).toHaveCount(0)
    await expect(page.getByRole("link", { name: "Chatbots" })).toHaveAttribute(
      "aria-current",
      "page",
    )

    await page.goto("/saas/invitations/accept?token=one-time-secret")
    await expect(page).toHaveURL("/app/invitations/accept")
    await expect(page.getByLabel("Invitation token")).toHaveValue("one-time-secret")
    await expect(page.getByRole("heading", { level: 1, name: "Accept invitation" })).toHaveCount(1)
    await expect(
      page.getByRole("heading", { level: 1, name: "Welcome to RAG Studio" }),
    ).toHaveCount(0)
    await expect(page.locator(".rs-shell__desktop-nav [aria-current='page']")).toHaveCount(0)
    expect(await page.locator("body").innerText()).not.toContain("one-time-secret")
    await page.getByLabel("Invitation token").fill("")
    await page.screenshot({ fullPage: true, path: resolve(evidenceRoot, "neutral-invitation.png") })

    await page.goto("/saas/workspaces/not-a-uuid/private/raw-value")
    await expect(page).toHaveURL("/app/not-found")
    await expect(page.getByRole("heading", { level: 1, name: "Page unavailable" })).toHaveCount(1)
    await expect(
      page.getByRole("heading", { level: 1, name: "Welcome to RAG Studio" }),
    ).toHaveCount(0)
    await expect(page.locator(".rs-shell__desktop-nav [aria-current='page']")).toHaveCount(0)
    expect(await page.locator("body").innerText()).not.toContain("not-a-uuid")
    await page.screenshot({ fullPage: true, path: resolve(evidenceRoot, "neutral-not-found.png") })
  })

  test("unauthenticated entry renders recovery inside the canonical shell", async ({ page }) => {
    // Given: no recoverable browser session.
    await page.route("**/api/saas/auth/session", (route) =>
      route.fulfill({ contentType: "application/json", json: {}, status: 401 }),
    )
    await page.route("**/api/saas/auth/refresh", (route) =>
      route.fulfill({ contentType: "application/json", json: {}, status: 401 }),
    )

    // When: the product entry loads.
    await page.goto("/app")

    // Then: authentication is recoverable without mounting a second shell.
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible()
    await expect(page.locator(".rs-shell")).toHaveCount(1)
    await expect(page.locator(".rs-saas-shell")).toHaveCount(0)
  })

  test("captures the canonical shell at every required locale and viewport", async ({ page }) => {
    // Given: the exact production build and a disposable confirmed Workspace context.
    await mockAuthenticatedBff(page)
    await mkdir(evidenceRoot, { recursive: true })
    const matrix = [
      { height: 800, locale: "en", name: "en-360", width: 360 },
      { height: 1024, locale: "en", name: "en-768", width: 768 },
      { height: 900, locale: "en", name: "en-1440", width: 1440 },
      { height: 800, locale: "ru", name: "ru-360", width: 360 },
      { height: 1024, locale: "ru", name: "ru-768", width: 768 },
      { height: 900, locale: "ru", name: "ru-1440", width: 1440 },
    ] as const

    for (const row of matrix) {
      // When: each required locale and responsive width renders.
      await page.setViewportSize({ height: row.height, width: row.width })
      await page.goto(`/app?lang=${row.locale}`)
      await expect(page.locator(".rs-shell")).toBeVisible()

      // Then: the shell has no horizontal overflow and a fresh screenshot is captured.
      const overflow = await page.evaluate(() =>
        [...document.querySelectorAll<HTMLElement>("body *")]
          .map((element) => ({ element, rect: element.getBoundingClientRect() }))
          .filter(({ element, rect }) =>
            element.classList.contains("rs-visually-hidden")
              ? false
              : rect.left < -0.5 || rect.right > window.innerWidth + 0.5,
          )
          .map(({ element, rect }) => ({
            className: element.className,
            left: rect.left,
            right: rect.right,
            tagName: element.tagName,
          })),
      )
      expect(overflow).toEqual([])
      await page.screenshot({ fullPage: true, path: resolve(evidenceRoot, `${row.name}.png`) })
    }
  })
})

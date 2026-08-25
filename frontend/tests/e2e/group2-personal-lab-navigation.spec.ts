import { mkdir } from "node:fs/promises"
import { resolve } from "node:path"
import { expect, type Page, test } from "@playwright/test"

const accountId = "00000000-0000-4000-8000-000000000030"
const workspaceId = "00000000-0000-4000-8000-000000000031"
const evidenceRoot = resolve(
  process.cwd(),
  "..",
  ".omo",
  "evidence",
  "group-2-personal-lab",
  "task-6",
  "browser",
)

const account = {
  id: accountId,
  label: "Private account",
  owner: null,
  status: "active",
  workspaces: [{ id: workspaceId, name: "Team workspace", role: "member" }],
} as const

async function mockSession(page: Page, workspace: boolean): Promise<void> {
  await page.route("**/api/saas/auth/session", (route) =>
    route.fulfill({
      contentType: "application/json",
      json: {
        user_id: "00000000-0000-4000-8000-000000000003",
        email: "personal-navigation@redacted.invalid",
        accounts: [account],
        active_account_id: accountId,
        workspace: workspace ? { id: workspaceId, name: "Team workspace", role: "member" } : null,
      },
    }),
  )
  await page.route("**/api/saas/auth/csrf", (route) => route.fulfill({ status: 204 }))
  await page.route("**/health", (route) =>
    route.fulfill({ contentType: "application/json", json: { status: "ok" } }),
  )
}

async function personalNavigation(page: Page) {
  if (await page.locator(".rs-shell__desktop-nav").isVisible()) {
    return page.locator(".rs-shell__desktop-nav")
  }
  await page.locator(".rs-shell__menu").click()
  return page.locator(".rs-shell__drawer-nav")
}

async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(1)
}

test.describe("Group 2 Personal Lab navigation", () => {
  test("captures Home to Knowledge at every required locale and viewport", async ({ page }) => {
    // Given: a server-confirmed Personal Lab and the approved responsive matrix.
    await mockSession(page, false)
    await mkdir(evidenceRoot, { recursive: true })
    const consoleErrors: string[] = []
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text())
    })
    const matrix = [
      { height: 800, locale: "en", names: ["Knowledge", "Home"], width: 360 },
      { height: 1024, locale: "en", names: ["Knowledge", "Home"], width: 768 },
      { height: 900, locale: "en", names: ["Knowledge", "Home"], width: 1440 },
      { height: 800, locale: "ru", names: ["Знания", "Главная"], width: 360 },
      { height: 1024, locale: "ru", names: ["Знания", "Главная"], width: 768 },
      { height: 900, locale: "ru", names: ["Знания", "Главная"], width: 1440 },
    ] as const

    for (const row of matrix) {
      // When: Home loads and the user follows its real Knowledge destination.
      await page.setViewportSize({ height: row.height, width: row.width })
      await page.goto(`/app?lang=${row.locale}`)
      await expect(page.locator(".rs-shell")).toHaveCount(1)
      await expect(page.locator(".rs-personal-home")).toBeVisible()
      await expectNoHorizontalOverflow(page)
      await page.screenshot({
        fullPage: true,
        path: resolve(evidenceRoot, `${row.locale}-${row.width}-home.png`),
      })

      const navigation = await personalNavigation(page)
      await navigation.getByRole("link", { name: row.names[0], exact: true }).click()

      // Then: the direct route is active without a duplicate page title or overflow.
      await expect(page).toHaveURL("/app/knowledge")
      await expect(page.locator(".rs-personal-knowledge")).toBeVisible()
      await expect(page.getByRole("heading", { level: 1, name: row.names[0] })).toHaveCount(0)
      await expect(page.locator("a[href='/app/knowledge'][aria-current='page']")).toHaveCount(1)
      await expect(page.locator("a[href='/app']").first()).toBeVisible()
      await expectNoHorizontalOverflow(page)
      await page.screenshot({
        fullPage: true,
        path: resolve(evidenceRoot, `${row.locale}-${row.width}-knowledge.png`),
      })
    }
    expect(consoleErrors).toEqual([])
  })

  test("hides Personal navigation for Workspace, missing context, denial, and sign-out", async ({
    browser,
  }, testInfo) => {
    // Given/When: each non-Personal authority state opens a Personal deep link.
    const baseURL = testInfo.project.use.baseURL
    if (typeof baseURL !== "string") throw new Error("Playwright baseURL is required")

    const workspaceContext = await browser.newContext()
    const workspacePage = await workspaceContext.newPage()
    await mockSession(workspacePage, true)
    await workspacePage.goto(`${baseURL}/app/knowledge?lang=en`)
    await expect(workspacePage.getByText("Page unavailable")).toBeVisible()
    await expect(workspacePage.locator("a[href='/app/knowledge']")).toHaveCount(0)
    await workspaceContext.close()

    const missingContext = await browser.newContext()
    const missingPage = await missingContext.newPage()
    await missingPage.route("**/api/saas/auth/session", (route) =>
      route.fulfill({
        contentType: "application/json",
        json: {
          user_id: "00000000-0000-4000-8000-000000000003",
          email: "personal-navigation@redacted.invalid",
          accounts: [account],
          active_account_id: null,
          workspace: null,
        },
      }),
    )
    await missingPage.route("**/api/saas/auth/csrf", (route) => route.fulfill({ status: 204 }))
    await missingPage.goto(`${baseURL}/app/knowledge?lang=en`)
    await expect(missingPage.getByText("No context is available yet.")).toBeVisible()
    await expect(missingPage.locator("a[href='/app/knowledge']")).toHaveCount(0)
    await missingContext.close()

    const deniedContext = await browser.newContext()
    const deniedPage = await deniedContext.newPage()
    await deniedPage.route("**/api/saas/auth/session", (route) => route.fulfill({ status: 403 }))
    await deniedPage.goto(`${baseURL}/app/knowledge?lang=en`)
    await expect(
      deniedPage.getByText(
        "You no longer have access to this context. Choose an available context.",
      ),
    ).toBeVisible()
    await expect(deniedPage.locator("a[href='/app/knowledge']")).toHaveCount(0)
    await deniedContext.close()

    const signedOutContext = await browser.newContext()
    await signedOutContext.addCookies([
      { name: "ragstudio-development-csrf", url: baseURL, value: "test-proof" },
    ])
    const signedOutPage = await signedOutContext.newPage()
    await signedOutPage.route("**/api/saas/auth/session", (route) =>
      route.fulfill({ contentType: "application/json", json: {}, status: 401 }),
    )
    await signedOutPage.route("**/api/saas/auth/refresh", (route) =>
      route.fulfill({ contentType: "application/json", json: {}, status: 401 }),
    )
    await signedOutPage.goto(`${baseURL}/app/knowledge?lang=en`)

    // Then: signed-out recovery is public and every state withheld false Personal links.
    await expect(signedOutPage).toHaveURL(/\/sign-in$/u)
    await expect(signedOutPage.locator("a[href='/app/knowledge']")).toHaveCount(0)
    await signedOutContext.close()
  })
})

import { mkdir } from "node:fs/promises"
import { resolve } from "node:path"
import { expect, type Page, test } from "@playwright/test"

const accountId = "00000000-0000-4000-8000-000000000020"
const workspaceId = "00000000-0000-4000-8000-000000000021"
const evidenceRoot = resolve(
  process.cwd(),
  "..",
  ".omo",
  "evidence",
  "group-1-unified-rag-studio-shell-auth",
  "mobile-signout-fix",
)

async function mockAuthenticatedSession(page: Page): Promise<void> {
  await page.route("**/api/saas/auth/session", (route) =>
    route.fulfill({
      contentType: "application/json",
      json: {
        user_id: "00000000-0000-4000-8000-000000000002",
        email: "compact-shell@redacted.invalid",
        accounts: [
          {
            id: accountId,
            label: "Compact shell",
            owner: null,
            status: "active",
            workspaces: [{ id: workspaceId, name: "Compact shell", role: "owner" }],
          },
        ],
        active_account_id: accountId,
        workspace: { id: workspaceId, name: "Compact shell", role: "owner" },
      },
    }),
  )
  await page.route("**/api/saas/auth/csrf", (route) => route.fulfill({ status: 204 }))
}

test("keeps the compact shell separated and exposes keyboard-reachable sign out", async ({
  page,
}) => {
  await mockAuthenticatedSession(page)
  await mkdir(evidenceRoot, { recursive: true })

  await page.setViewportSize({ height: 945, width: 1001 })
  await page.goto("/app/chat")
  await expect(page.locator(".rs-shell")).toBeVisible()
  await expect(page.locator(".rs-shell__desktop-nav")).toBeHidden()
  await expect(page.locator(".rs-shell__menu")).toBeVisible()
  await expect(page.locator(".rs-shell__brand")).toBeVisible()
  await page.screenshot({ path: resolve(evidenceRoot, "compact-1001-before-menu.png") })

  await page.locator(".rs-shell__menu").click()
  const drawer = page.getByRole("dialog", { name: /navigation/i })
  await expect(drawer).toBeVisible()
  await expect(drawer.getByRole("button", { name: /sign out/i })).toBeVisible()
  await page.screenshot({ path: resolve(evidenceRoot, "compact-1001-menu-signout.png") })

  await page.setViewportSize({ height: 900, width: 1440 })
  await page.goto("/app/chat")
  await expect(page.locator(".rs-shell__desktop-nav")).toBeVisible()
  await expect(page.locator(".rs-shell__menu")).toBeHidden()
  await page.locator(".rs-shell__user-menu summary").click()
  await expect(page.getByRole("button", { name: /sign out/i })).toBeVisible()
  await page.screenshot({ path: resolve(evidenceRoot, "desktop-1440-user-menu.png") })
})

import { mkdir } from "node:fs/promises"
import { resolve } from "node:path"
import { expect, test } from "@playwright/test"

const evidenceRoot = resolve(
  process.cwd(),
  "..",
  ".omo",
  "evidence",
  "group-1-unified-rag-studio-shell-auth",
  "task-8",
  "auth-layout-fix",
  "visual",
)

const matrix = [
  { height: 1366, locale: "en", width: 2560 },
  { height: 1366, locale: "ru", width: 2560 },
  { height: 900, locale: "en", width: 1440 },
  { height: 900, locale: "ru", width: 1440 },
  { height: 1024, locale: "en", width: 768 },
  { height: 1024, locale: "ru", width: 768 },
  { height: 800, locale: "en", width: 360 },
  { height: 800, locale: "ru", width: 360 },
] as const

test.describe("canonical authentication composition", () => {
  for (const row of matrix) {
    test(`keeps intro and form separate at ${row.width}px in ${row.locale}`, async ({ page }) => {
      // Given: the unified shell cannot recover an authenticated session.
      await page.route("**/api/saas/auth/session", (route) =>
        route.fulfill({ contentType: "application/json", json: {}, status: 401 }),
      )
      await page.route("**/api/saas/auth/refresh", (route) =>
        route.fulfill({ contentType: "application/json", json: {}, status: 401 }),
      )
      await mkdir(evidenceRoot, { recursive: true })
      await page.setViewportSize({ height: row.height, width: row.width })

      // When: the canonical authentication page settles at the target viewport.
      await page.goto(`/app?lang=${row.locale}`)
      const auth = page.locator(".rs-public-auth")
      const intro = page.locator(".rs-public-auth__hero")
      const card = page.locator(".rs-public-auth__form-panel")
      await expect(card).toBeVisible()

      // Then: both regions stay inside the auth surface with a readable gap.
      const [authBox, introBox, cardBox] = await Promise.all([
        auth.boundingBox(),
        intro.boundingBox(),
        card.boundingBox(),
      ])
      expect(authBox).not.toBeNull()
      expect(introBox).not.toBeNull()
      expect(cardBox).not.toBeNull()
      if (authBox === null || introBox === null || cardBox === null) return

      expect(introBox.x).toBeGreaterThanOrEqual(authBox.x)
      expect(cardBox.x + cardBox.width).toBeLessThanOrEqual(authBox.x + authBox.width)
      if (row.width > 900) {
        expect(introBox.width).toBeGreaterThanOrEqual(400)
        expect(introBox.x + introBox.width + 32).toBeLessThanOrEqual(cardBox.x)
      } else {
        expect(introBox.y + introBox.height + 24).toBeLessThanOrEqual(cardBox.y)
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
        row.width,
      )
      await page.screenshot({
        fullPage: true,
        path: resolve(evidenceRoot, `auth-${row.locale}-${row.width}.png`),
      })
    })
  }
})

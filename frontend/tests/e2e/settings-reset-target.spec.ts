import { expect, test } from "@playwright/test"
import { mockAuthenticatedGroup1Session } from "./group1-auth-fixture"

const viewports = [
  { height: 1024, name: "tablet", width: 768 },
  { height: 900, name: "desktop", width: 1440 },
] as const

test.describe("Settings Reset to default target", () => {
  test.beforeEach(async ({ page }) => {
    await mockAuthenticatedGroup1Session(page)
  })

  for (const viewport of viewports) {
    test(`is at least 44px at ${viewport.name}`, async ({ page }) => {
      await page.setViewportSize({ height: viewport.height, width: viewport.width })
      await page.goto("/settings?lang=en")
      const reset = page.locator(".rs-settings-reset-prompt")
      await expect(reset).toBeVisible()

      const geometry = await reset.evaluate((element) => {
        const bounds = element.getBoundingClientRect()
        const styles = getComputedStyle(element)
        return {
          height: bounds.height,
          minBlockSize: styles.minBlockSize,
          minHeight: styles.minHeight,
        }
      })
      expect(geometry.minHeight).toBe("44px")
      expect(geometry.height).toBeGreaterThanOrEqual(44)
    })
  }
})

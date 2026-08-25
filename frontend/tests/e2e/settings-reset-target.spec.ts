import { expect, test } from "@playwright/test"

const viewports = [
  { height: 1024, name: "tablet", width: 768 },
  { height: 900, name: "desktop", width: 1440 },
] as const

test.describe("Settings Reset to default target", () => {
  test.beforeEach(async ({ page }) => {
    await page.route("**/api/saas/auth/session", (route) =>
      route.fulfill({
        contentType: "application/json",
        json: {
          user_id: "00000000-0000-4000-8000-000000000002",
          email: "personal-settings@redacted.invalid",
          accounts: [
            {
              id: "00000000-0000-4000-8000-000000000020",
              label: "Private account",
              owner: null,
              status: "active",
              workspaces: [],
            },
          ],
          active_account_id: "00000000-0000-4000-8000-000000000020",
          workspace: null,
        },
      }),
    )
    await page.route("**/api/personal/settings", (route) =>
      route.fulfill({
        contentType: "application/json",
        json: {
          api_key: "********",
          provider: "deepseek",
          model: "deepseek-chat",
          temperature: 1,
          max_tokens: 2048,
          system_prompt: "Answer from context.",
          top_k: 5,
          chunk_size: 512,
          chunk_overlap: 64,
          chunking: {
            schema_version: 1,
            strategy: "recursive",
            chunk_size: 512,
            chunk_overlap: 64,
            parent_size: 2048,
            window_sentences: 2,
          },
        },
      }),
    )
    await page.route("**/api/personal/settings/models/deepseek", (route) =>
      route.fulfill({
        contentType: "application/json",
        json: { provider: "deepseek", models: ["deepseek-chat"], cached: true },
      }),
    )
    await page.route("**/api/saas/auth/csrf", (route) => route.fulfill({ status: 204 }))
  })

  for (const viewport of viewports) {
    test(`is at least 44px at ${viewport.name}`, async ({ page }) => {
      await page.setViewportSize({ height: viewport.height, width: viewport.width })
      await page.goto("/app/settings?lang=en")
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

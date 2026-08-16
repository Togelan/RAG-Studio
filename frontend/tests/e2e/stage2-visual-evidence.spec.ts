import { expect, type Page, type TestInfo, test } from "@playwright/test"
import { attachBundleIdentity } from "./task18-identity"

const viewports = [
  { name: "360x800", width: 360, height: 800 },
  { name: "768x1024", width: 768, height: 1024 },
  { name: "1440x900", width: 1440, height: 900 },
] as const
async function attachViewport(page: Page, name: string, testInfo: TestInfo): Promise<void> {
  if (testInfo.project.name !== "chromium") return
  const screenshotPath = testInfo.outputPath(`${name}.png`)
  await page.screenshot({ fullPage: false, path: screenshotPath, type: "png" })
  await testInfo.attach(`${name}.png`, {
    path: screenshotPath,
    contentType: "image/png",
  })
}

async function attachTopViewport(page: Page, name: string, testInfo: TestInfo): Promise<void> {
  if (testInfo.project.name !== "chromium") return
  await page.evaluate(() => {
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur()
    globalThis.scrollTo({ behavior: "auto", left: 0, top: 0 })
  })
  await expect.poll(() => page.evaluate(() => globalThis.scrollY)).toBe(0)
  await attachViewport(page, name, testInfo)
}

async function expectExactViewport(
  page: Page,
  viewport: (typeof viewports)[number],
): Promise<void> {
  await expect(
    page.evaluate(() => ({ height: globalThis.innerHeight, width: globalThis.innerWidth })),
  ).resolves.toEqual({ height: viewport.height, width: viewport.width })
  await expect(
    page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    ),
  ).resolves.toBe(true)
}

test.beforeEach(async ({ browser }, testInfo) => {
  void browser
  await attachBundleIdentity(testInfo)
})

test("captures source-current Stage 2 responsive states", async ({ page }, testInfo) => {
  test.setTimeout(120_000)

  await page.route("**/api/ingest/documents**", async (route) => {
    const request = route.request()
    if (request.method() !== "GET" || !/\/api\/ingest\/documents(?:\?|$)/u.test(request.url())) {
      await route.continue()
      return
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        documents: [
          {
            chunk_overlap: 64,
            chunk_size: 512,
            chunks_count: 1,
            created_at: "2026-08-15T00:00:00Z",
            doc_id: "qa-doc-task18",
            filename: "stage2-browser-qa.md",
            schema_version: 1,
            strategy: "recursive",
          },
        ],
        next_cursor: null,
        total: 1,
        truncated: false,
      }),
      status: 200,
    })
  })
  await page.goto("/settings?lang=ru")
  await page.waitForLoadState("networkidle")
  await expect(page.locator(".rs-document h3")).toHaveText("stage2-browser-qa.md")

  for (const viewport of viewports) {
    await page.setViewportSize({ height: viewport.height, width: viewport.width })

    await page.goto("/?lang=ru")
    await expect(page.locator("h1")).toBeVisible()
    await expectExactViewport(page, viewport)
    await attachViewport(page, `welcome-ru-${viewport.name}`, testInfo)

    await page.goto("/settings?lang=ru")
    const maxTokens = page.locator("#settings-max-tokens")
    await expect(maxTokens).toBeVisible()
    await expect(page.locator(".rs-document")).toBeVisible()
    await expect(page.locator(".rs-document h3")).toHaveText("stage2-browser-qa.md")
    const nextValue = (await maxTokens.inputValue()) === "4096" ? "2048" : "4096"
    await maxTokens.selectOption(nextValue)
    const savebar = page.locator(".rs-settings-savebar")
    await expect(savebar).toHaveClass(/rs-settings-savebar--sticky/u)
    await savebar.locator('button[type="submit"]').click()
    await expect(savebar).not.toHaveClass(/rs-settings-savebar--sticky/u)
    await expect(
      savebar.evaluate((element) => {
        const ingestion = document.querySelector(".rs-ingestion")
        if (ingestion === null) return false
        return (
          getComputedStyle(element).position !== "sticky" &&
          element.getBoundingClientRect().bottom <= ingestion.getBoundingClientRect().top
        )
      }),
    ).resolves.toBe(true)
    await savebar.scrollIntoViewIfNeeded()
    await expectExactViewport(page, viewport)
    await attachViewport(page, `settings-ru-saved-${viewport.name}`, testInfo)

    await page.goto("/chat?lang=ru")
    const newChat = page.locator(".rs-chat__new:visible")
    const sidebarToggle = page.locator(".rs-chat__sidebar-toggle")
    await expect
      .poll(async () => (await newChat.count()) > 0 || (await sidebarToggle.isVisible()))
      .toBe(true)
    if ((await newChat.count()) === 0) {
      await expect(sidebarToggle).toBeVisible()
      await sidebarToggle.click()
      await expect(newChat).toBeVisible()
    }
    await newChat.click()
    const composer = page.locator(".rs-chat__composer-input")
    await expect(composer).toBeEnabled()
    await composer.fill("Покажи тестовый источник")
    await page.locator(".rs-chat__composer button").click()
    const response = page.locator(".rs-chat__message--assistant:not(.rs-chat__message--streaming)")
    await expect(response).toBeVisible()
    await response.locator("details summary").click()
    await expect(response.locator("details")).toHaveAttribute("open", "")
    await expect(response.locator(".rs-chat__citation")).toContainText("qa-fixture.md")
    await page.locator(".rs-chat__composer-wrap").evaluate((element) => {
      element.scrollIntoView({ block: "end" })
    })
    await expect(
      page.locator(".rs-chat__composer-meta").evaluate((element) => {
        const bottomNav = document.querySelector(".rs-shell__bottom-nav")
        if (bottomNav === null || getComputedStyle(bottomNav).display === "none") return true
        return element.getBoundingClientRect().bottom <= bottomNav.getBoundingClientRect().top
      }),
    ).resolves.toBe(true)
    await expectExactViewport(page, viewport)
    await attachTopViewport(page, `chat-ru-done-${viewport.name}`, testInfo)
  }
})

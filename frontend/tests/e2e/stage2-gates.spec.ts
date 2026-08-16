import { existsSync } from "node:fs"
import { resolve } from "node:path"
import { fileURLToPath } from "node:url"
import AxeBuilder from "@axe-core/playwright"
import { expect, type Page, test } from "@playwright/test"
import { attachBundleIdentity } from "./task18-identity"

const viewports = [
  { name: "mobile", width: 360, height: 800 },
  { name: "tablet", width: 768, height: 1024 },
  { name: "desktop", width: 1440, height: 900 },
] as const
const frontendRoot = resolve(fileURLToPath(new URL(".", import.meta.url)), "..", "..")
const task18EvidenceRoot = resolve(
  frontendRoot,
  "..",
  ".omo",
  "evidence",
  "ulw",
  "stage2-react-fr012-parity-01a000f9",
  "G001-execute-the-approved-stage-2-plan-at",
  "a1",
  "task-18-playwright",
)
test("writes Playwright artifacts outside frontend lint inputs", ({ browser }, testInfo) => {
  expect(browser.version()).not.toBe("")
  expect(testInfo.project.outputDir.startsWith(task18EvidenceRoot)).toBe(true)
  expect(testInfo.project.outputDir).toMatch(/[\\/]artifacts$/u)
  expect(existsSync(resolve(frontendRoot, ".omo"))).toBe(false)
})

test.beforeEach(async ({ browser }, testInfo) => {
  void browser
  await attachBundleIdentity(testInfo)
})

const routes = [
  { path: "/", heading: /welcome to rag studio/i, workspace: false },
  { path: "/settings", heading: /^settings$/i, workspace: false },
  { path: "/chat", heading: /^chat$/i, workspace: true },
] as const

async function openPage(
  page: Page,
  path: string,
  viewport: (typeof viewports)[number],
): Promise<void> {
  await page.setViewportSize({ height: viewport.height, width: viewport.width })
  await page.goto(`${path}?lang=en`)
  await expect(page.locator("h1")).toBeVisible()
}

async function assertNoOverflow(page: Page): Promise<void> {
  await expect(
    page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    ),
  ).resolves.toBe(true)
}

async function mockDocuments(page: Page): Promise<void> {
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
}

test.describe("Stage 2 responsive shell", () => {
  for (const viewport of viewports) {
    for (const route of routes) {
      test(`${route.path} is responsive at ${viewport.name}`, async ({ page }) => {
        await openPage(page, route.path, viewport)

        await expect(page.locator("h1")).toHaveText(route.heading)
        await expect(page.locator(".rs-shell")).toHaveClass(
          route.workspace ? /rs-shell--workspace/ : /^rs-shell$/,
        )
        const disabledDashboard = page.locator(".rs-shell__nav-link--disabled")
        await expect(disabledDashboard).toHaveCount(2)
        await expect(
          disabledDashboard.evaluateAll((elements) =>
            elements.every((element) => !element.hasAttribute("href")),
          ),
        ).resolves.toBe(true)
        await expect(page.locator(".rs-health")).not.toBeEmpty()
        await assertNoOverflow(page)

        const undersizedTargets = await page
          .locator(
            ".rs-shell a[href], .rs-shell button, .rs-shell select, .rs-shell input:not([type=hidden]), .rs-shell textarea, .rs-shell [role=button]",
          )
          .evaluateAll((elements) =>
            elements.flatMap((element) => {
              const rect = element.getBoundingClientRect()
              if (element.classList.contains("rs-visually-hidden")) return []
              if (rect.width === 0 || rect.height === 0) return []
              if (rect.width >= 44 && rect.height >= 44) return []
              return [
                {
                  ariaLabel: element.getAttribute("aria-label"),
                  className: element.getAttribute("class"),
                  height: rect.height,
                  name: element.textContent?.trim().slice(0, 80),
                  tagName: element.tagName,
                  width: rect.width,
                },
              ]
            }),
          )
        expect(undersizedTargets).toEqual([])

        if (route.workspace) {
          const geometry = await page.evaluate(() => {
            const rect = (selector: string): number | null =>
              document.querySelector(selector)?.getBoundingClientRect().width ?? null
            return {
              chatWorkspace: rect(".rs-chat__workspace"),
              main: rect(".rs-shell__main"),
              messageStack: rect(".rs-chat__message-stack"),
            }
          })
          const expectedOuterWidth = Math.min(viewport.width - 32, 1280)
          expect(geometry.main).toBeCloseTo(expectedOuterWidth, 0)
          expect(geometry.chatWorkspace).toBeCloseTo(expectedOuterWidth, 0)
          expect(geometry.messageStack ?? 0).toBeLessThanOrEqual(680)

          const newChat = page.locator(".rs-chat__new:visible")
          if ((await newChat.count()) === 0) {
            await page.locator(".rs-chat__sidebar-toggle").click()
            await expect(newChat).toBeVisible()
          }
          await newChat.click()
          const composer = page.locator(".rs-chat__composer-input")
          await expect(composer).toBeEnabled()
          await composer.fill("Покажи тестовый источник")
          await page.locator(".rs-chat__composer button").click()
          const response = page.locator(
            ".rs-chat__message--assistant:not(.rs-chat__message--streaming)",
          )
          await expect(response).toBeVisible()
          await expect(response.locator("details")).toHaveCount(1)
          await response.locator("details summary").click()
          await expect(response.locator("details")).toHaveAttribute("open", "")
          await expect(response.locator(".rs-chat__citation")).toContainText("qa-fixture.md")
        }
      })
    }
  }

  for (const viewport of viewports) {
    test(`Settings saved state retains the document table at ${viewport.name}`, async ({
      page,
    }) => {
      await mockDocuments(page)
      await openPage(page, "/settings", viewport)
      await expect(page.locator(".rs-document h3")).toHaveText("stage2-browser-qa.md")
      await expect(page.locator(".rs-document")).toContainText(/recursive/iu)

      const maxTokens = page.locator("#settings-max-tokens")
      const nextValue = (await maxTokens.inputValue()) === "4096" ? "2048" : "4096"
      await maxTokens.selectOption(nextValue)
      const savebar = page.locator(".rs-settings-savebar")
      await expect(savebar).toHaveClass(/rs-settings-savebar--sticky/u)
      await savebar.locator('button[type="submit"]').click()
      await expect(savebar).not.toHaveClass(/rs-settings-savebar--sticky/u)
      await expect(page.locator(".rs-document h3")).toHaveText("stage2-browser-qa.md")
      await expect(page.locator(".rs-document")).toContainText(/recursive/iu)
    })
  }

  test("mobile touch drawer returns focus and reduced motion stays bounded", async ({ page }) => {
    await openPage(page, "/chat", viewports[0])
    await page.emulateMedia({ reducedMotion: "reduce" })
    const menu = page.locator(".rs-shell__menu")
    await menu.tap()
    const dialog = page.getByRole("dialog")
    await expect(dialog).toBeVisible()
    for (let index = 0; index < 8; index += 1) {
      await page.keyboard.press("Tab")
      await expect
        .poll(() => dialog.evaluate((element) => element.contains(document.activeElement)))
        .toBe(true)
    }
    await page.keyboard.press("Escape")
    await expect(dialog).toHaveCount(0)
    await expect(menu).toBeFocused()
    await expect(
      page.locator(".rs-shell").evaluate((element) => {
        const duration = getComputedStyle(element).transitionDuration
        return duration === "0s" || Number.parseFloat(duration) <= 0.01
      }),
    ).resolves.toBe(true)

    await page.locator(".rs-shell__menu").tap()
    const reopenedDialog = page.getByRole("dialog")
    await expect(reopenedDialog).toBeVisible()
    await page.keyboard.press("Shift+Tab")
    await expect
      .poll(() => reopenedDialog.evaluate((element) => element.contains(document.activeElement)))
      .toBe(true)
    await page.keyboard.press("Escape")
    await expect(reopenedDialog).toHaveCount(0)
  })
})

test.describe("@a11y WCAG 2 AA", () => {
  const a11yRoutes = [
    { path: "/", page: "Welcome" },
    { path: "/settings", page: "Settings" },
    { path: "/chat", page: "Chat" },
  ] as const

  for (const viewport of viewports) {
    for (const route of a11yRoutes) {
      test(`${route.page} has no applicable axe violations at ${viewport.name}`, async ({
        page,
      }) => {
        await openPage(page, route.path, viewport)
        const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze()
        expect(results.violations).toEqual([])
        await expect(page.getByRole("combobox", { name: /language selector/i })).toBeVisible()
        const menu = page.locator(".rs-shell__menu")
        if (await menu.isVisible()) await expect(menu).toHaveAccessibleName(/toggle menu/i)
        else await expect(menu).toHaveAttribute("aria-label", /toggle menu/i)
      })
    }
  }
})

test.describe("@perf locale and first-paint timing", () => {
  test("renders first paint and switches EN/RU within the local thresholds", async ({
    page,
  }, testInfo) => {
    await page.addInitScript(() => {
      const firstContentfulPaint = "__stage2FirstContentfulPaint"
      new PerformanceObserver((entries) => {
        const paint = entries.getEntries().find((entry) => entry.name === "first-contentful-paint")
        if (paint !== undefined) Reflect.set(globalThis, firstContentfulPaint, paint.startTime)
      }).observe({ buffered: true, type: "paint" })
    })
    await page.goto("/?lang=en")
    await expect(page.locator("h1")).toBeVisible()
    const firstPaint = await page.evaluate(() => {
      const observed = Reflect.get(globalThis, "__stage2FirstContentfulPaint")
      const buffered = performance
        .getEntriesByType("paint")
        .find((entry) => entry.name === "first-contentful-paint")
      if (typeof observed === "number") return observed
      if (buffered !== undefined) return buffered.startTime
      throw new Error("first-contentful-paint entry is unavailable")
    })
    expect(firstPaint).toBeLessThan(1000)

    await page.evaluate(() => {
      const select = document.querySelector<HTMLSelectElement>("#locale-select")
      const heading = document.querySelector("h1")
      if (select === null) {
        throw new Error("Locale selector is unavailable")
      }
      if (heading === null) {
        throw new Error("Page heading is unavailable")
      }
      const coherentRussianDom = (): boolean =>
        document.documentElement.lang === "ru" &&
        heading.textContent?.includes("Добро пожаловать") === true
      const markOptimisticDom = (): void => {
        if (
          coherentRussianDom() &&
          document.documentElement.dataset.localeOptimisticDomAt === undefined
        ) {
          document.documentElement.dataset.localeOptimisticDomAt = String(performance.now())
        }
      }
      select.addEventListener(
        "change",
        () => {
          document.documentElement.dataset.localeOptimisticStart = String(performance.now())
        },
        { once: true },
      )
      new MutationObserver(markOptimisticDom).observe(document.documentElement, {
        attributes: true,
        childList: true,
        characterData: true,
        subtree: true,
      })
    })
    const localeResponse = page.waitForResponse(
      (response) =>
        response.url().endsWith("/api/ui/locale") &&
        response.request().method() === "POST" &&
        response.status() === 200,
    )
    await page.getByRole("combobox", { name: /language selector/i }).selectOption("ru")
    await expect(page.locator("html")).toHaveAttribute("lang", "ru")
    await expect(page.locator("h1")).toHaveText(/Добро пожаловать/u)
    const optimisticUiToDom = await page.evaluate(() => {
      const start = Number(document.documentElement.dataset.localeOptimisticStart)
      const end = Number(document.documentElement.dataset.localeOptimisticDomAt)
      return end - start
    })
    expect(optimisticUiToDom).toBeLessThan(50)

    await localeResponse
    await page.evaluate(() => {
      document.documentElement.dataset.localeResponseObservedAt = String(performance.now())
      const heading = document.querySelector("h1")
      const markFinalDom = (): void => {
        if (
          document.documentElement.lang === "ru" &&
          heading?.textContent?.includes("Добро пожаловать") === true
        ) {
          document.documentElement.dataset.localeFinalDomAt = String(performance.now())
        }
      }
      markFinalDom()
      new MutationObserver(markFinalDom).observe(document.documentElement, {
        attributes: true,
        childList: true,
        characterData: true,
        subtree: true,
      })
    })
    await expect(page.locator("html")).toHaveAttribute("lang", "ru")
    await expect(page.locator("h1")).toHaveText(/Добро пожаловать/u)
    const postResponseToFinalDom = await page.evaluate(() => {
      const response = Number(document.documentElement.dataset.localeResponseObservedAt)
      const finalDom = Number(document.documentElement.dataset.localeFinalDomAt)
      return finalDom - response
    })
    expect(postResponseToFinalDom).toBeLessThan(100)

    await page.goto("/chat?lang=ru")
    await page.locator(".rs-chat__new").click()
    const composer = page.getByRole("textbox")
    await expect(composer).toBeEnabled()
    await composer.fill("漢".repeat(240))
    await expect(composer).toHaveValue("漢".repeat(240))
    await assertNoOverflow(page)
    await testInfo.attach("stage2-timing.json", {
      body: JSON.stringify({
        cjkCharacters: 240,
        firstPaint,
        optimisticUiToDom,
        postResponseToFinalDom,
        project: testInfo.project.name,
      }),
      contentType: "application/json",
    })
  })
})

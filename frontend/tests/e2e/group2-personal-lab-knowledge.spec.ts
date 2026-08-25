import { expect, type Page, test } from "@playwright/test"

const accountId = "00000000-0000-4000-8000-000000000070"
const documentId = "00000000-0000-4000-8000-000000000071"
const fileId = "00000000-0000-4000-8000-000000000072"
const settings = {
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
} as const

async function mockPersonalSession(page: Page, identity: string): Promise<void> {
  await page.route("**/api/saas/auth/session", (route) =>
    route.fulfill({
      contentType: "application/json",
      json: {
        user_id: identity,
        email: `${identity}@redacted.invalid`,
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
        workspace: null,
      },
    }),
  )
  await page.route("**/health", (route) =>
    route.fulfill({ contentType: "application/json", json: { status: "ok" } }),
  )
  await page.route("**/api/saas/auth/csrf", (route) =>
    route.fulfill({
      headers: { "Set-Cookie": "ragstudio-development-csrf=fixture-proof; Path=/" },
      status: 204,
    }),
  )
  await page.route("**/api/personal/settings/models/deepseek", (route) =>
    route.fulfill({
      contentType: "application/json",
      json: { provider: "deepseek", models: ["deepseek-chat"], cached: true },
    }),
  )
}

test.describe("Group 2 Personal Knowledge", () => {
  test("drives chunks, duplicate actions, stale-CSRF recovery, and Chat readiness", async ({
    context,
    page,
  }) => {
    await mockPersonalSession(page, "00000000-0000-4000-8000-000000000073")
    const actions: string[] = []
    const csrfHeaders: string[] = []
    let staleRejected = false
    await context.addCookies([
      { name: "ragstudio-development-csrf", url: "http://127.0.0.1:5191", value: "proof-a" },
    ])
    await page.route("**/api/saas/auth/csrf", (route) =>
      route.fulfill(
        staleRejected
          ? {
              headers: { "Set-Cookie": "ragstudio-development-csrf=fresh; Path=/" },
              status: 204,
            }
          : { status: 204 },
      ),
    )
    await page.route("**/api/personal/settings", (route) =>
      route.fulfill({ contentType: "application/json", json: settings }),
    )
    await page.route("**/api/personal/knowledge/documents", (route) =>
      route.fulfill({
        contentType: "application/json",
        json: {
          documents: [
            { doc_id: documentId, filename: "private.txt", chunk_count: 1, strategy: "recursive" },
          ],
          next_cursor: null,
          truncated: false,
        },
      }),
    )
    await page.route("**/api/personal/knowledge/documents/**/chunks**", (route) =>
      route.fulfill({
        contentType: "application/json",
        json: {
          chunks: [{ point_id: "p1", chunk_index: 0, text: "Scoped chunk preview." }],
          next_cursor: null,
          truncated: false,
        },
      }),
    )
    await page.route("**/api/personal/knowledge/progress/**", (route) =>
      route.fulfill({
        contentType: "application/json",
        json: { file_id: fileId, status: "complete", code: null },
      }),
    )
    await page.route("**/api/personal/knowledge/upload**", async (route) => {
      const header = route.request().headers()["x-csrf-token"] ?? ""
      csrfHeaders.push(header)
      const action = new URL(route.request().url()).searchParams.get("action") ?? "default"
      actions.push(action)
      if (header === "proof-a") {
        staleRejected = true
        await route.fulfill({
          contentType: "application/json",
          json: { detail: "stale" },
          status: 403,
        })
        return
      }
      if (action === "default") {
        await route.fulfill({
          contentType: "application/json",
          status: 409,
          json: {
            status: "duplicate",
            filename: "private.txt",
            existing_chunks: 1,
            existing_size: 7,
            stored_chunk_size: 512,
            stored_chunk_overlap: 64,
            new_file_size: 7,
            estimated_chunks: 1,
            chunks_settings_changed: false,
            current_chunk_size: 512,
            current_chunk_overlap: 64,
          },
        })
        return
      }
      await route.fulfill({
        contentType: "application/json",
        status: 201,
        json: {
          status: "processing",
          file_id: fileId,
          message: "Upload accepted.",
          doc_id: documentId,
          filename: "private.txt",
          chunk_count: 1,
        },
      })
    })
    await page.route("**/api/personal/chat/sessions", (route) =>
      route.fulfill({ contentType: "application/json", json: [] }),
    )

    await page.goto("/app/knowledge?lang=en")
    await page.getByRole("button", { name: "Chunks" }).click()
    await expect(page.getByText("Scoped chunk preview.")).toBeVisible()

    const file = { name: "private.txt", mimeType: "text/plain", buffer: Buffer.from("private") }
    await page.locator("input[type='file']").setInputFiles(file)
    await expect(page.getByRole("dialog", { name: "Duplicate File Detected" })).toBeVisible()
    await page.getByRole("button", { name: "Upload as new" }).click()
    await expect.poll(() => actions).toContain("rename")
    await page.locator("input[type='file']").setInputFiles(file)
    await page.getByRole("button", { name: "Replace" }).click()
    await expect.poll(() => actions).toContain("replace")
    expect(csrfHeaders).toEqual(expect.arrayContaining(["proof-a", "fresh"]))

    await page.goto("/app/settings?lang=en")
    await expect(page.getByLabel("API Key")).toHaveAttribute("placeholder", "••••••••")
    await expect(page.getByText("Knowledge index")).toHaveCount(0)
    await expect(page.getByRole("button", { name: "Browse files" })).toHaveCount(0)
    await page.goto("/app/chat?lang=en")
    await expect(page.getByLabel("Message input")).toBeVisible()
    await expect(page.getByRole("button", { name: "+ New Chat" })).toBeVisible()
  })

  test("atomically saves chunking and reports a controlled re-index failure", async ({ page }) => {
    await mockPersonalSession(page, "00000000-0000-4000-8000-000000000074")
    const saves: Record<string, unknown>[] = []
    await page.route("**/api/personal/settings", async (route) => {
      if (route.request().method() === "GET")
        return route.fulfill({ contentType: "application/json", json: settings })
      const body = route.request().postDataJSON() as Record<string, unknown>
      saves.push(body)
      const { api_key: _apiKey, ...response } = body
      return route.fulfill({
        contentType: "application/json",
        json: { ...response, api_key: "********", chunks_changed: true },
      })
    })
    await page.route("**/api/personal/knowledge/documents", (route) =>
      route.fulfill({
        contentType: "application/json",
        json: {
          documents: [
            { doc_id: "ok", filename: "ok.txt", chunk_count: 1, strategy: "recursive" },
            { doc_id: "fail", filename: "fail.txt", chunk_count: 1, strategy: "recursive" },
          ],
          next_cursor: null,
          truncated: false,
        },
      }),
    )
    await page.route("**/api/personal/knowledge/documents/**/reindex", (route) =>
      route.request().url().includes("/fail/")
        ? route.fulfill({ status: 503 })
        : route.fulfill({
            contentType: "application/json",
            json: { status: "processing", file_id: "reindex-ok", message: "queued" },
          }),
    )
    await page.route("**/api/personal/knowledge/progress/reindex-ok", (route) =>
      route.fulfill({
        contentType: "application/json",
        json: {
          file_id: "reindex-ok",
          status: "done",
          message: "done",
          chunks_count: 1,
          error: null,
        },
      }),
    )

    await page.goto("/app/settings?lang=en")
    await page.getByLabel("Chunk Size", { exact: true }).selectOption("1024")
    await page.getByRole("button", { name: "Save Settings" }).click()
    await page.getByRole("button", { name: "Re-ingest All" }).click()
    await expect(page.getByText("Re-ingestion completed with errors.")).toBeVisible()
    expect(saves).toHaveLength(1)
    const saved = saves[0]
    if (saved === undefined) throw new Error("expected one atomic settings save")
    expect((saved.chunking as Record<string, unknown>).chunk_size).toBe(1024)
  })

  test("keeps Settings and sources isolated across two browser identities", async ({ browser }) => {
    for (const [identity, prompt, filename] of [
      ["00000000-0000-4000-8000-000000000076", "Identity A prompt", "a.txt"],
      ["00000000-0000-4000-8000-000000000077", "Identity B prompt", "b.txt"],
    ] as const) {
      const context = await browser.newContext()
      const page = await context.newPage()
      await mockPersonalSession(page, identity)
      await page.route("**/api/personal/settings", (route) =>
        route.fulfill({
          contentType: "application/json",
          json: { ...settings, system_prompt: prompt },
        }),
      )
      await page.route("**/api/personal/knowledge/documents", (route) =>
        route.fulfill({
          contentType: "application/json",
          json: {
            documents: [{ doc_id: identity, filename, chunk_count: 1, strategy: "recursive" }],
            next_cursor: null,
            truncated: false,
          },
        }),
      )
      await page.route("**/api/personal/knowledge/documents/**/chunks**", (route) =>
        route.fulfill({
          contentType: "application/json",
          json: { detail: "Not found" },
          status: 404,
        }),
      )
      await page.goto("/app/settings?lang=en")
      await expect(page.getByLabel("System Prompt")).toHaveValue(prompt)
      await page.goto("/app/knowledge?lang=en")
      await expect(page.getByText(filename)).toBeVisible()
      await expect(page.getByText(filename === "a.txt" ? "b.txt" : "a.txt")).toHaveCount(0)
      const foreignId = identity.endsWith("76") ? "foreign-b" : "foreign-a"
      expect(
        await page.evaluate(async (docId) => {
          return (await fetch(`/api/personal/knowledge/documents/${docId}/chunks`)).status
        }, foreignId),
      ).toBe(404)
      await context.close()
    }
  })
})

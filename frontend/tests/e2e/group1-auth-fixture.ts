import type { Page } from "@playwright/test"

const accountId = "00000000-0000-4000-8000-000000000020"
const workspaceId = "00000000-0000-4000-8000-000000000021"

export async function mockAuthenticatedGroup1Session(page: Page): Promise<void> {
  await page.route("**/api/saas/auth/session", (route) =>
    route.fulfill({
      contentType: "application/json",
      json: {
        user_id: "00000000-0000-4000-8000-000000000002",
        email: "stage2-parity@redacted.invalid",
        accounts: [
          {
            id: accountId,
            label: "Stage 2 parity",
            owner: {
              can_manage_billing: true,
              can_view_limits: true,
              can_view_plan: true,
            },
            status: "active",
            workspaces: [{ id: workspaceId, name: "Stage 2 parity", role: "owner" }],
          },
        ],
        active_account_id: accountId,
        workspace: { id: workspaceId, name: "Stage 2 parity", role: "owner" },
      },
    }),
  )
}

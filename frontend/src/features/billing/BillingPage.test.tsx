import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ApiContractError, ApiError } from "../../api/errors"
import { BillingPage } from "./BillingPage"
import type { BillingGateway, BillingProjection, BillingState } from "./billing-api"

let locale: "en" | "ru" = "en"

vi.mock("../../app/locale-provider", () => ({
  useLocaleContext: () => ({ locale, t: (key: string) => key }),
}))

const inactiveProjection: BillingProjection = {
  plan: { amount_usd_cents: 1_000, currency: "USD", interval: "month" },
  status: "none",
  pending: false,
  entitled: false,
  can_manage: false,
}

function gateway(overrides: Partial<BillingGateway> = {}): BillingGateway {
  return {
    checkout: vi.fn(() => Promise.resolve({ url: "https://checkout.example.test/session" })),
    load: vi.fn(() => Promise.resolve(inactiveProjection)),
    portal: vi.fn(() => Promise.resolve({ url: "https://billing.example.test/portal" })),
    ...overrides,
  }
}

afterEach(() => {
  cleanup()
  locale = "en"
})

describe("BillingPage", () => {
  it("labels local demo access without implying Stripe payment or entitlement", async () => {
    const localDemo: BillingState = {
      access: "demo",
      mode: "local_demo",
      plan: { amount_usd_cents: 1_000, currency: "USD", interval: "month" },
      stripe_configured: false,
    }
    render(
      <BillingPage
        gateway={gateway({
          load: vi.fn(() => Promise.resolve(localDemo)),
        })}
      />,
    )

    expect(await screen.findByText("billing_local_demo_title")).toBeVisible()
    expect(screen.getByText("$10 USD")).toBeVisible()
    expect(screen.getByText("billing_interval_month")).toBeVisible()
    expect(screen.getByText("billing_local_demo_access")).toBeVisible()
    expect(screen.queryByRole("button", { name: "billing_checkout" })).toBeNull()
    expect(screen.queryByRole("button", { name: "billing_portal" })).toBeNull()
    expect(document.body).not.toHaveTextContent("billing_status_active")
  })

  it("renders loading before the server projection and never infers paid state", () => {
    render(
      <BillingPage
        gateway={gateway({ load: vi.fn(() => new Promise<BillingProjection>(() => undefined)) })}
      />,
    )

    expect(screen.getByRole("status")).toHaveTextContent("billing_loading")
    expect(screen.queryByText("billing_status_active")).toBeNull()
    expect(screen.queryByRole("button", { name: "billing_checkout" })).toBeNull()
  })

  it("renders the inactive EN projection with Checkout enabled and Portal disabled", async () => {
    render(<BillingPage gateway={gateway()} />)

    expect(await screen.findByText("billing_plan_name")).toBeVisible()
    expect(screen.getByText("$10 USD")).toBeVisible()
    expect(screen.getByText("billing_status_none")).toBeVisible()
    expect(screen.getByRole("button", { name: "billing_checkout" })).toBeEnabled()
    expect(screen.getByRole("button", { name: "billing_portal" })).toBeDisabled()
    expect(document.body).not.toHaveTextContent("price_")
  })

  it("renders the verified active RU projection without offering another Checkout", async () => {
    locale = "ru"
    const active: BillingProjection = {
      ...inactiveProjection,
      status: "active",
      entitled: true,
      can_manage: true,
    }

    render(<BillingPage gateway={gateway({ load: vi.fn(() => Promise.resolve(active)) })} />)

    expect(await screen.findByText("billing_status_active")).toBeVisible()
    expect(screen.getByRole("button", { name: "billing_checkout" })).toBeDisabled()
    expect(screen.getByRole("button", { name: "billing_portal" })).toBeEnabled()
    expect(screen.getByTestId("billing-locale")).toHaveAttribute("lang", "ru")
  })

  it("keeps Checkout disabled while the verified projection is pending", async () => {
    const pending: BillingProjection = {
      ...inactiveProjection,
      status: "incomplete",
      pending: true,
      can_manage: true,
    }

    render(<BillingPage gateway={gateway({ load: vi.fn(() => Promise.resolve(pending)) })} />)

    expect(await screen.findByText("billing_status_incomplete")).toBeVisible()
    expect(screen.getByRole("button", { name: "billing_checkout" })).toBeDisabled()
    expect(screen.getByRole("button", { name: "billing_portal" })).toBeEnabled()
  })

  it("exposes visible native focus order for available billing actions", async () => {
    const user = userEvent.setup()
    render(<BillingPage gateway={gateway()} />)

    const checkout = await screen.findByRole("button", { name: "billing_checkout" })
    await user.tab()

    expect(checkout).toHaveFocus()
  })

  it.each([
    new ApiError(401, "sanitized", null),
    new ApiError(403, "sanitized", null),
    new ApiError(503, "sanitized", null),
    new ApiContractError(),
  ])("fails closed for a rejected or malformed projection", async (error) => {
    render(<BillingPage gateway={gateway({ load: vi.fn(() => Promise.reject(error)) })} />)

    expect(await screen.findByRole("alert")).toHaveTextContent("billing_unavailable")
    expect(screen.queryByText("billing_status_active")).toBeNull()
    expect(screen.getByRole("button", { name: "billing_retry" })).toBeEnabled()
    expect(screen.queryByRole("button", { name: "billing_checkout" })).toBeNull()
  })

  it("replaces an action label while pending and prevents duplicate Checkout", async () => {
    const user = userEvent.setup()
    let resolveCheckout: ((value: { readonly url: string }) => void) | undefined
    const checkout = vi.fn(
      () =>
        new Promise<{ readonly url: string }>((resolve) => {
          resolveCheckout = resolve
        }),
    )
    const navigateToHosted = vi.fn()
    render(<BillingPage gateway={gateway({ checkout })} navigateToHosted={navigateToHosted} />)
    const action = await screen.findByRole("button", { name: "billing_checkout" })

    await user.click(action)
    expect(screen.getByRole("button", { name: "billing_redirecting" })).toBeDisabled()
    await user.click(screen.getByRole("button", { name: "billing_redirecting" }))
    expect(checkout).toHaveBeenCalledOnce()

    resolveCheckout?.({ url: "https://checkout.example.test/session" })
    await waitFor(() =>
      expect(navigateToHosted).toHaveBeenCalledWith("https://checkout.example.test/session"),
    )
  })

  it("keeps a failed hosted action recoverable without changing entitlement", async () => {
    const user = userEvent.setup()
    render(
      <BillingPage
        gateway={gateway({ checkout: vi.fn(() => Promise.reject(new ApiError(503, "x", null))) })}
        navigateToHosted={vi.fn()}
      />,
    )

    await user.click(await screen.findByRole("button", { name: "billing_checkout" }))

    expect(await screen.findByRole("alert")).toHaveTextContent("billing_action_failed")
    expect(screen.getByText("billing_status_none")).toBeVisible()
    expect(screen.getByRole("button", { name: "billing_checkout" })).toBeEnabled()
  })
})

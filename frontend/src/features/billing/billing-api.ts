import { z } from "zod"

import { type ApiClient, apiClient } from "../../api/client"

const BillingPlanSchema = z
  .object({
    amount_usd_cents: z.literal(1_000),
    currency: z.literal("USD"),
    interval: z.literal("month"),
  })
  .strict()

const BillingStatusSchema = z.enum([
  "none",
  "incomplete",
  "active",
  "past_due",
  "canceled",
  "unpaid",
])

export const BillingProjectionSchema = z
  .object({
    plan: BillingPlanSchema,
    status: BillingStatusSchema,
    pending: z.boolean(),
    entitled: z.boolean(),
    can_manage: z.boolean(),
  })
  .strict()
  .superRefine((projection, context) => {
    if (projection.pending !== (projection.status === "incomplete")) {
      context.addIssue({ code: "custom", message: "Invalid pending projection" })
    }
    if (projection.entitled !== (projection.status === "active")) {
      context.addIssue({ code: "custom", message: "Invalid entitlement projection" })
    }
  })

export const LocalDemoBillingProjectionSchema = z
  .object({
    access: z.literal("demo"),
    mode: z.literal("local_demo"),
    plan: BillingPlanSchema,
    stripe_configured: z.literal(false),
  })
  .strict()

const BillingStateSchema = z.union([BillingProjectionSchema, LocalDemoBillingProjectionSchema])

const HostedBillingDestinationSchema = z
  .object({
    url: z
      .string()
      .url()
      .refine((value) => new URL(value).protocol === "https:"),
  })
  .strict()

export type BillingProjection = z.infer<typeof BillingProjectionSchema>
export type BillingState = z.infer<typeof BillingStateSchema>
export type HostedBillingDestination = z.infer<typeof HostedBillingDestinationSchema>

export type BillingGateway = {
  readonly load: (signal?: AbortSignal) => Promise<BillingState>
  readonly checkout: () => Promise<HostedBillingDestination>
  readonly portal: () => Promise<HostedBillingDestination>
}

export function createBillingGateway(client: ApiClient = apiClient): BillingGateway {
  return {
    load: (signal) =>
      client.get(
        "/api/personal/billing",
        BillingStateSchema,
        signal === undefined ? {} : { signal },
      ),
    checkout: () =>
      client.post("/api/personal/billing/checkout", {}, HostedBillingDestinationSchema),
    portal: () => client.post("/api/personal/billing/portal", {}, HostedBillingDestinationSchema),
  }
}

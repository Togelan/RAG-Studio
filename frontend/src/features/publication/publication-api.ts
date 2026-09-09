import { z } from "zod"

import { type ApiClient, apiClient } from "../../api/client"

export const MONTHLY_WIDGET_MESSAGE_LIMIT = 500

type ExactOriginResult = { readonly ok: true; readonly origin: string } | { readonly ok: false }

export function parseExactOrigin(value: string): ExactOriginResult {
  if (value !== value.trim() || value.includes("*")) {
    return { ok: false }
  }
  try {
    const parsed = new URL(value)
    const schemeBoundary = value.indexOf("://")
    const authority = schemeBoundary < 0 ? "" : value.slice(schemeBoundary + 3)
    if (
      (parsed.protocol !== "http:" && parsed.protocol !== "https:") ||
      authority === "" ||
      /[/?#]/u.test(authority) ||
      parsed.username !== "" ||
      parsed.password !== "" ||
      parsed.hostname === "localhost" ||
      parsed.hostname.endsWith(".localhost") ||
      parsed.hostname.includes(":") ||
      parsed.hostname === "127.0.0.1"
    ) {
      return { ok: false }
    }
    return { ok: true, origin: parsed.origin }
  } catch (error) {
    if (error instanceof TypeError) return { ok: false }
    throw error
  }
}

const ExactOriginSchema = z.string().superRefine((value, context) => {
  if (!parseExactOrigin(value).ok) {
    context.addIssue({ code: "custom", message: "Invalid exact origin" })
  }
})

export const PublicationProjectionSchema = z
  .object({
    publication_id: z.string().uuid(),
    public_key: z.string().uuid(),
    allowed_origin: ExactOriginSchema,
    state: z.enum(["enabled", "disabled", "revoked"]),
    key_version: z.number().int().positive(),
    audit_event_count: z.number().int().nonnegative(),
  })
  .strict()

export const LocalDemoWidgetProjectionSchema = z
  .object({
    mode: z.literal("local_demo"),
    protected_preview: z.literal(true),
    public_publication: z.literal(false),
  })
  .strict()

const WidgetStateSchema = z.union([PublicationProjectionSchema, LocalDemoWidgetProjectionSchema])

export type PublicationProjection = z.infer<typeof PublicationProjectionSchema>
export type WidgetState = z.infer<typeof WidgetStateSchema>

export type PublicationGateway = {
  readonly load: (signal?: AbortSignal) => Promise<WidgetState>
  readonly publish: (allowedOrigin: string) => Promise<PublicationProjection>
  readonly disable: () => Promise<PublicationProjection>
  readonly revoke: () => Promise<PublicationProjection>
}

export function createPublicationGateway(client: ApiClient = apiClient): PublicationGateway {
  const path = "/api/personal/widget-publication"
  return {
    load: (signal) => client.get(path, WidgetStateSchema, signal === undefined ? {} : { signal }),
    publish: (allowedOrigin) =>
      client.put(path, { allowed_origin: allowedOrigin }, PublicationProjectionSchema),
    disable: () => client.post(`${path}/disable`, {}, PublicationProjectionSchema),
    revoke: () => client.delete(path, PublicationProjectionSchema),
  }
}

export function buildEmbedSnippet(publicKey: string, applicationOrigin: string): string {
  const apiBaseUrl = new URL(applicationOrigin).origin
  const scriptUrl = new URL("/widget/rag-studio-widget.v1.js", apiBaseUrl).href
  return [
    `<script src="${scriptUrl}" defer></script>`,
    `<rag-studio-widget widget-key="${publicKey}" api-base-url="${apiBaseUrl}"></rag-studio-widget>`,
  ].join("\n")
}

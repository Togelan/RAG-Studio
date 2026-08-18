import type { Locale } from "../../i18n/locale-inventory"

export const workspaceRoles = ["owner", "admin", "member"] as const
export type WorkspaceRole = (typeof workspaceRoles)[number]

export type WorkspaceSummary = {
  readonly id: string
  readonly name: string
  readonly role: WorkspaceRole
}

export type Credentials = {
  readonly email: string
  readonly password: string
}

export type AuthMode = "sign-in" | "sign-up"

export type AuthStatus =
  | { readonly kind: "ready" }
  | { readonly kind: "pending" }
  | { readonly kind: "confirmation-required" }
  | { readonly kind: "error"; readonly message: string }

export type SaasLocale = Locale

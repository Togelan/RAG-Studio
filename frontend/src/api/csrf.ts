import { apiErrorFromResponse } from "./errors"

export type CsrfProofOptions = {
  readonly establish: () => Promise<Response>
  readonly readToken: () => string | null
}

const csrfCookieNames = ["__Host-ragstudio-csrf", "ragstudio-development-csrf"] as const

export function browserCsrfToken(): string | null {
  if (typeof document === "undefined") {
    return null
  }
  const cookies = document.cookie.split(";").map((part) => part.trim())
  for (const name of csrfCookieNames) {
    const prefix = `${name}=`
    const cookie = cookies.find((part) => part.startsWith(prefix))
    if (cookie !== undefined) {
      return decodeURIComponent(cookie.slice(prefix.length))
    }
  }
  return null
}

export function requiresCsrfProof(path: string): boolean {
  if (path.startsWith("/api/saas/") || path.startsWith("/api/personal/")) {
    return true
  }
  return ["/api/settings", "/api/ingest", "/api/chat"].some(
    (root) => path === root || path.startsWith(`${root}/`),
  )
}

function headersForToken(path: string, token: string | null): Readonly<Record<string, string>> {
  return requiresCsrfProof(path) && token !== null && token !== "" ? { "X-CSRF-Token": token } : {}
}

export function csrfHeadersForPath(path: string): Readonly<Record<string, string>> {
  return headersForToken(path, browserCsrfToken())
}

export async function csrfHeadersForMutation(
  path: string,
  options: CsrfProofOptions,
): Promise<Readonly<Record<string, string>>> {
  const current = headersForToken(path, options.readToken())
  if (Object.keys(current).length > 0 || !requiresCsrfProof(path)) {
    return current
  }

  const response = await options.establish()
  if (!response.ok) {
    throw apiErrorFromResponse(response)
  }
  const established = headersForToken(path, options.readToken())
  if (Object.keys(established).length === 0) {
    throw apiErrorFromResponse(new Response(null, { status: 403 }))
  }
  return established
}

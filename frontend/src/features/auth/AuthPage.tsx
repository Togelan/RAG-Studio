import { useState } from "react"

import { Button } from "../../components/ui/button"
import { Card, CardContent } from "../../components/ui/card"
import { Input } from "../../components/ui/input"
import { Label } from "../../components/ui/label"
import type { Locale } from "../../i18n/locale-inventory"
import { authActionLabel } from "../saas/saas-copy"
import "../saas/saas.css"
import type { Credentials } from "./auth-contracts"
import { getAuthCopy } from "./auth-copy"

export type AuthMode = "sign-in" | "sign-up"

export type AuthStatus =
  | { readonly kind: "ready" }
  | { readonly kind: "pending" }
  | { readonly kind: "confirmation-required" }
  | { readonly kind: "error"; readonly message?: string }

export function AuthPage({
  locale,
  mode,
  onAuthenticate,
  onModeChange,
  status,
}: {
  readonly locale: Locale
  readonly mode: AuthMode
  readonly onAuthenticate: (credentials: Credentials) => Promise<void>
  readonly onModeChange: (mode: AuthMode) => void
  readonly status: AuthStatus
}): React.JSX.Element {
  const copy = getAuthCopy(locale)
  const heroLabel = copy.productLabel.replace("RAG-Studio", "RAG‑Studio")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const pending = status.kind === "pending"
  const alternateMode: AuthMode = mode === "sign-in" ? "sign-up" : "sign-in"

  const submit = (event: React.FormEvent<HTMLFormElement>): void => {
    event.preventDefault()
    void onAuthenticate({ email, password })
  }

  return (
    <section aria-labelledby="public-auth-title" className="rs-public-auth__panel">
      <header className="rs-public-auth__hero">
        <h1 id="public-auth-title">{heroLabel}</h1>
        <p>{copy.introduction}</p>
      </header>
      <div className="rs-public-auth__form-panel">
        <h2>{authActionLabel(locale, mode)}</h2>
        <Card className="rs-public-auth__card">
          <CardContent>
            <form className="rs-saas-form" onSubmit={submit}>
              <div className="rs-saas-field">
                <Label htmlFor="auth-email">{copy.email}</Label>
                <Input
                  autoComplete="email"
                  disabled={pending}
                  id="auth-email"
                  onChange={(event) => setEmail(event.currentTarget.value)}
                  required
                  type="email"
                  value={email}
                />
              </div>
              <div className="rs-saas-field">
                <Label htmlFor="auth-password">{copy.password}</Label>
                <Input
                  autoComplete={mode === "sign-in" ? "current-password" : "new-password"}
                  disabled={pending}
                  id="auth-password"
                  minLength={8}
                  onChange={(event) => setPassword(event.currentTarget.value)}
                  required
                  type="password"
                  value={password}
                />
              </div>
              {status.kind === "error" ? (
                <p className="rs-saas-notice rs-saas-notice--error" role="alert">
                  {copy.authError}
                </p>
              ) : null}
              {status.kind === "confirmation-required" ? (
                <p className="rs-saas-notice rs-saas-notice--success" role="status">
                  {copy.confirmationRequired}
                </p>
              ) : null}
              <Button className="rs-saas-form__submit" disabled={pending} type="submit">
                {pending ? copy.submitting : authActionLabel(locale, mode)}
              </Button>
            </form>
            <div className="rs-saas-auth__alternate">
              <span>{mode === "sign-in" ? copy.signInPrompt : copy.signUpPrompt}</span>
              <Button onClick={() => onModeChange(alternateMode)} variant="secondary">
                {authActionLabel(locale, alternateMode)}
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </section>
  )
}

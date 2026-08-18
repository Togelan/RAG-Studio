import { KeyRound, Sparkles } from "lucide-react"
import { useState } from "react"

import { Button } from "../../../components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card"
import { Input } from "../../../components/ui/input"
import { Label } from "../../../components/ui/label"
import type { AuthMode, AuthStatus, Credentials, SaasLocale } from "../model"
import { authActionLabel, getSaasCopy } from "../saas-copy"
import "../saas.css"

export function AuthPage({
  locale,
  mode,
  onAuthenticate,
  onModeChange,
  status,
}: {
  readonly locale: SaasLocale
  readonly mode: AuthMode
  readonly onAuthenticate: (credentials: Credentials) => Promise<void>
  readonly onModeChange: (mode: AuthMode) => void
  readonly status: AuthStatus
}): React.JSX.Element {
  const copy = getSaasCopy(locale)
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const pending = status.kind === "pending"
  const alternateMode: AuthMode = mode === "sign-in" ? "sign-up" : "sign-in"

  const submit = (event: React.FormEvent<HTMLFormElement>): void => {
    event.preventDefault()
    void onAuthenticate({ email, password })
  }

  return (
    <main className="rs-saas-auth">
      <div className="rs-saas-auth__atmosphere" aria-hidden="true" />
      <section className="rs-saas-auth__intro">
        <span className="rs-saas-eyebrow">
          <Sparkles aria-hidden="true" size={16} />
          RAG-STUDIO
        </span>
        <h1>{copy.productLabel}</h1>
        <p>
          {locale === "en"
            ? "A trusted place to configure and test your company knowledge assistants."
            : "Надёжное место для настройки и проверки помощников на знаниях компании."}
        </p>
      </section>
      <Card className="rs-saas-auth__card">
        <CardHeader>
          <span className="rs-saas-auth__icon" aria-hidden="true">
            <KeyRound size={20} />
          </span>
          <CardTitle>{authActionLabel(locale, mode)}</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="rs-saas-form" onSubmit={submit}>
            <div className="rs-saas-field">
              <Label htmlFor="saas-email">{copy.email}</Label>
              <Input
                autoComplete="email"
                disabled={pending}
                id="saas-email"
                onChange={(event) => setEmail(event.currentTarget.value)}
                required
                type="email"
                value={email}
              />
            </div>
            <div className="rs-saas-field">
              <Label htmlFor="saas-password">{copy.password}</Label>
              <Input
                autoComplete={mode === "sign-in" ? "current-password" : "new-password"}
                disabled={pending}
                id="saas-password"
                minLength={8}
                onChange={(event) => setPassword(event.currentTarget.value)}
                required
                type="password"
                value={password}
              />
            </div>
            {status.kind === "error" ? (
              <p className="rs-saas-notice rs-saas-notice--error" role="alert">
                {status.message || copy.authError}
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
    </main>
  )
}

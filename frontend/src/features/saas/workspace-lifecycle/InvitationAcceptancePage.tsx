import { Check, MailCheck } from "lucide-react"
import { useState } from "react"

import { Button } from "../../../components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card"
import { Input } from "../../../components/ui/input"
import { Label } from "../../../components/ui/label"
import type { SaasLocale } from "../model"
import type { WorkspaceSummaryResponse } from "../workspaces/workspace-api"
import {
  createWorkspaceLifecycleGateway,
  type WorkspaceLifecycleGateway,
} from "./workspace-lifecycle-api"
import { getWorkspaceLifecycleCopy } from "./workspace-lifecycle-copy"

const defaultGateway = createWorkspaceLifecycleGateway()

export function InvitationAcceptancePage({
  gateway = defaultGateway,
  initialToken,
  locale,
  onAccepted,
}: {
  readonly gateway?: WorkspaceLifecycleGateway
  readonly initialToken: string
  readonly locale: SaasLocale
  readonly onAccepted: (workspace: WorkspaceSummaryResponse) => Promise<void>
}): React.JSX.Element {
  const labels = getWorkspaceLifecycleCopy(locale)
  const [token, setToken] = useState(initialToken)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState(false)

  const accept = async (event: React.FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault()
    setPending(true)
    setError(false)
    try {
      await onAccepted(await gateway.acceptInvitation(token.trim()))
    } catch {
      setError(true)
    } finally {
      setPending(false)
    }
  }

  return (
    <main className="rs-saas-start">
      <Card className="rs-saas-start__card">
        <CardHeader>
          <span className="rs-saas-auth__icon" aria-hidden="true">
            <MailCheck size={20} />
          </span>
          <CardTitle>{labels.accept}</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="rs-workspace-invitation__description">{labels.acceptDescription}</p>
          <form className="rs-saas-form" onSubmit={(event) => void accept(event)}>
            <div className="rs-saas-field">
              <Label htmlFor="workspace-invitation-token">{labels.invitationToken}</Label>
              <Input
                autoComplete="off"
                disabled={pending}
                id="workspace-invitation-token"
                minLength={43}
                onChange={(event) => setToken(event.currentTarget.value)}
                required
                value={token}
              />
            </div>
            {error ? (
              <p className="rs-saas-notice rs-saas-notice--error" role="alert">
                {labels.mutationError}
              </p>
            ) : null}
            <Button disabled={pending || token.trim().length < 43} type="submit">
              <Check aria-hidden="true" size={17} />
              {labels.accept}
            </Button>
          </form>
        </CardContent>
      </Card>
    </main>
  )
}

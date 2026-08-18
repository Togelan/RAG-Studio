import { MailPlus, ShieldCheck, UserRound } from "lucide-react"
import { useEffect, useState } from "react"

import { Button } from "../../../components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card"
import { Input } from "../../../components/ui/input"
import { Label } from "../../../components/ui/label"
import { Select } from "../../../components/ui/select"
import type { SaasLocale, WorkspaceRole } from "../model"
import {
  canManageInvitations,
  createPeopleGateway,
  type Invitation,
  type InvitationRole,
  type Membership,
  type PeopleGateway,
} from "./people-api"
import { getPeopleCopy } from "./people-copy"

type PeopleState =
  | { readonly kind: "loading" }
  | { readonly kind: "error" }
  | {
      readonly kind: "ready"
      readonly invitations: readonly Invitation[]
      readonly members: readonly Membership[]
    }

const defaultGateway = createPeopleGateway()

export function PeoplePage({
  gateway = defaultGateway,
  locale,
  workspaceId,
  workspaceRole,
}: {
  readonly gateway?: PeopleGateway
  readonly locale: SaasLocale
  readonly workspaceId: string
  readonly workspaceRole: WorkspaceRole
}): React.JSX.Element {
  const labels = getPeopleCopy(locale)
  const [email, setEmail] = useState("")
  const [inviteRole, setInviteRole] = useState<InvitationRole>("member")
  const [mutationPending, setMutationPending] = useState(false)
  const [state, setState] = useState<PeopleState>(() =>
    canManageInvitations(workspaceRole)
      ? { kind: "loading" }
      : { kind: "ready", invitations: [], members: [] },
  )

  useEffect(() => {
    if (!canManageInvitations(workspaceRole)) return
    let active = true
    const members =
      workspaceRole === "owner" ? gateway.listMembers(workspaceId) : Promise.resolve([])
    void Promise.all([gateway.listInvitations(workspaceId), members])
      .then(([invitations, loadedMembers]) => {
        if (active) setState({ kind: "ready", invitations, members: loadedMembers })
      })
      .catch(() => {
        if (active) setState({ kind: "error" })
      })
    return (): void => {
      active = false
    }
  }, [gateway, workspaceId, workspaceRole])

  if (!canManageInvitations(workspaceRole)) {
    return <p className="rs-saas-permission">{labels.denied}</p>
  }
  if (state.kind === "loading") {
    return (
      <p className="rs-saas-permission" aria-busy="true">
        {labels.loading}
      </p>
    )
  }
  if (state.kind === "error") {
    return (
      <p className="rs-saas-notice rs-saas-notice--error" role="alert">
        {labels.error}
      </p>
    )
  }

  const invite = async (event: React.FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault()
    setMutationPending(true)
    try {
      const invitation = await gateway.createInvitation(workspaceId, { email, role: inviteRole })
      setState({ ...state, invitations: [...state.invitations, invitation] })
      setEmail("")
    } finally {
      setMutationPending(false)
    }
  }

  const revokeInvitation = async (invitationId: string): Promise<void> => {
    setMutationPending(true)
    try {
      await gateway.revokeInvitation(workspaceId, invitationId)
      setState({ ...state, invitations: state.invitations.filter(({ id }) => id !== invitationId) })
    } finally {
      setMutationPending(false)
    }
  }

  return (
    <section className="rs-people">
      <header className="rs-people__heading">
        <span className="rs-saas-eyebrow">RAG-STUDIO</span>
        <h1>{labels.title}</h1>
        <p>{labels.description}</p>
      </header>
      <div className="rs-people__grid">
        <Card>
          <CardHeader>
            <MailPlus aria-hidden="true" size={20} />
            <CardTitle>{labels.inviteTitle}</CardTitle>
          </CardHeader>
          <CardContent>
            <form className="rs-saas-form" onSubmit={(event) => void invite(event)}>
              <div className="rs-saas-field">
                <Label htmlFor="invite-email">{labels.email}</Label>
                <Input
                  id="invite-email"
                  type="email"
                  required
                  disabled={mutationPending}
                  value={email}
                  onChange={(event) => setEmail(event.currentTarget.value)}
                />
              </div>
              <div className="rs-saas-field">
                <Label htmlFor="invite-role">{labels.role}</Label>
                <Select
                  id="invite-role"
                  disabled={mutationPending}
                  value={inviteRole}
                  onChange={(event) => setInviteRole(event.currentTarget.value as InvitationRole)}
                  options={[
                    { label: labels.member, value: "member" },
                    { label: labels.admin, value: "admin" },
                  ]}
                />
              </div>
              <Button type="submit" disabled={mutationPending || email.trim() === ""}>
                {mutationPending ? labels.sending : labels.send}
              </Button>
            </form>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <ShieldCheck aria-hidden="true" size={20} />
            <CardTitle>{labels.pending}</CardTitle>
          </CardHeader>
          <CardContent className="rs-people__records">
            {state.invitations.length === 0 ? (
              <p className="rs-people__empty">{labels.noInvitations}</p>
            ) : (
              state.invitations.map((invitation) => (
                <article className="rs-people__record" key={invitation.id}>
                  <div>
                    <strong>{invitation.email}</strong>
                    <span>
                      {invitation.role === "admin" ? labels.admin : labels.member} ·{" "}
                      {invitation.status}
                    </span>
                  </div>
                  <Button
                    variant="secondary"
                    disabled={mutationPending}
                    onClick={() => void revokeInvitation(invitation.id)}
                  >
                    {labels.revoke}
                  </Button>
                </article>
              ))
            )}
          </CardContent>
        </Card>
      </div>
      <Card>
        <CardHeader>
          <UserRound aria-hidden="true" size={20} />
          <CardTitle>{labels.active}</CardTitle>
        </CardHeader>
        <CardContent className="rs-people__records">
          {workspaceRole !== "owner" ? (
            <p className="rs-saas-permission">{labels.ownerOnly}</p>
          ) : state.members.length === 0 ? (
            <p className="rs-people__empty">{labels.noMembers}</p>
          ) : (
            state.members.map((member) => (
              <article className="rs-people__record" key={member.user_id}>
                <div>
                  <strong>{member.user_id}</strong>
                  <span>
                    {member.role === "owner"
                      ? labels.owner
                      : member.role === "admin"
                        ? labels.admin
                        : labels.member}
                  </span>
                </div>
              </article>
            ))
          )}
        </CardContent>
      </Card>
    </section>
  )
}

import { Archive, ArrowRightLeft } from "lucide-react"
import { useEffect, useState } from "react"

import { Button } from "../../../components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "../../../components/ui/dialog"
import { Label } from "../../../components/ui/label"
import { Select } from "../../../components/ui/select"
import type { SaasLocale, WorkspaceRole } from "../model"
import {
  createWorkspaceLifecycleGateway,
  type WorkspaceLifecycleGateway,
  type WorkspaceLifecycleMember,
} from "./workspace-lifecycle-api"
import { getWorkspaceLifecycleCopy } from "./workspace-lifecycle-copy"

type LifecycleAction = "archive" | "transfer"

type MemberState =
  | { readonly kind: "loading" }
  | { readonly kind: "error" }
  | { readonly kind: "ready"; readonly members: readonly WorkspaceLifecycleMember[] }

const defaultGateway = createWorkspaceLifecycleGateway()

export function WorkspaceLifecyclePanel({
  gateway = defaultGateway,
  locale,
  onArchived,
  onTransferred,
  workspaceId,
  workspaceName,
  workspaceRole,
}: {
  readonly gateway?: WorkspaceLifecycleGateway
  readonly locale: SaasLocale
  readonly onArchived: () => void
  readonly onTransferred: () => void
  readonly workspaceId: string
  readonly workspaceName: string
  readonly workspaceRole: WorkspaceRole
}): React.JSX.Element | null {
  const labels = getWorkspaceLifecycleCopy(locale)
  const [state, setState] = useState<MemberState>({ kind: "loading" })
  const [selectedUserId, setSelectedUserId] = useState("")
  const [confirmation, setConfirmation] = useState<LifecycleAction | null>(null)
  const [pending, setPending] = useState(false)
  const [mutationError, setMutationError] = useState(false)

  useEffect(() => {
    if (workspaceRole !== "owner") return
    let active = true
    void gateway
      .listMembers(workspaceId)
      .then((members) => {
        if (active) setState({ kind: "ready", members })
      })
      .catch(() => {
        if (active) setState({ kind: "error" })
      })
    return (): void => {
      active = false
    }
  }, [gateway, workspaceId, workspaceRole])

  if (workspaceRole !== "owner") return null

  const eligibleMembers =
    state.kind === "ready" ? state.members.filter(({ role }) => role === "admin") : []
  const canTransfer = selectedUserId !== "" && !pending

  const confirm = async (): Promise<void> => {
    if (confirmation === null) return
    setPending(true)
    setMutationError(false)
    try {
      if (confirmation === "transfer") {
        await gateway.transferOwnership(workspaceId, selectedUserId)
        onTransferred()
      } else {
        await gateway.archiveWorkspace(workspaceId)
        onArchived()
      }
      setConfirmation(null)
    } catch {
      setMutationError(true)
    } finally {
      setPending(false)
    }
  }

  return (
    <Card className="rs-workspace-lifecycle">
      <CardHeader>
        <ArrowRightLeft aria-hidden="true" size={20} />
        <CardTitle>{labels.lifecycle}</CardTitle>
      </CardHeader>
      <CardContent aria-busy={state.kind === "loading"} className="rs-workspace-lifecycle__content">
        <p>{labels.lifecycleDescription}</p>
        {state.kind === "error" ? (
          <p className="rs-saas-notice rs-saas-notice--error" role="alert">
            {labels.loadError}
          </p>
        ) : null}
        {state.kind === "ready" ? (
          <div className="rs-workspace-lifecycle__transfer">
            <Label htmlFor="workspace-new-owner">{labels.newOwner}</Label>
            <Select
              id="workspace-new-owner"
              disabled={pending || eligibleMembers.length === 0}
              onChange={(event) => setSelectedUserId(event.currentTarget.value)}
              options={eligibleMembers.map((member) => ({
                label: member.user_id,
                value: member.user_id,
              }))}
              value={selectedUserId}
            />
            {eligibleMembers.length === 0 ? <p>{labels.noEligibleMembers}</p> : null}
            <Button
              disabled={!canTransfer}
              onClick={() => setConfirmation("transfer")}
              variant="secondary"
            >
              <ArrowRightLeft aria-hidden="true" size={16} />
              {labels.transfer}
            </Button>
          </div>
        ) : null}
        <div className="rs-workspace-lifecycle__archive">
          <Button disabled={pending} onClick={() => setConfirmation("archive")} variant="danger">
            <Archive aria-hidden="true" size={16} />
            {labels.archive}
          </Button>
        </div>
        {mutationError ? (
          <p className="rs-saas-notice rs-saas-notice--error" role="alert">
            {labels.mutationError}
          </p>
        ) : null}
      </CardContent>
      {confirmation !== null ? (
        <Dialog open onOpenChange={(open) => !open && setConfirmation(null)}>
          <DialogContent>
            <DialogTitle>
              {confirmation === "transfer" ? labels.transferTitle : labels.archiveTitle}
            </DialogTitle>
            <DialogDescription>
              {confirmation === "transfer"
                ? labels.transferBody(selectedUserId)
                : labels.archiveBody(workspaceName)}
            </DialogDescription>
            <div className="rs-chatbots__actions">
              <Button disabled={pending} onClick={() => setConfirmation(null)} variant="secondary">
                {labels.cancel}
              </Button>
              <Button
                disabled={pending}
                onClick={() => void confirm()}
                variant={confirmation === "archive" ? "danger" : "primary"}
              >
                {confirmation === "transfer" ? labels.confirmTransfer : labels.confirmArchive}
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      ) : null}
    </Card>
  )
}

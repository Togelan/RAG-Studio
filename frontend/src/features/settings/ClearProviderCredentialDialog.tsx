import { useLocaleContext } from "../../app/locale-provider"
import { Button } from "../../components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "../../components/ui/dialog"

type ClearProviderCredentialDialogProps = {
  readonly error: boolean
  readonly onClose: () => void
  readonly onConfirm: () => void
  readonly open: boolean
  readonly pending: boolean
}

export function ClearProviderCredentialDialog({
  error,
  onClose,
  onConfirm,
  open,
  pending,
}: ClearProviderCredentialDialogProps): React.JSX.Element {
  const { t } = useLocaleContext()
  return (
    <Dialog
      onOpenChange={(nextOpen) => {
        if (!nextOpen && !pending) onClose()
      }}
      open={open}
    >
      <DialogContent aria-describedby="clear-provider-credential-description">
        <DialogTitle>{t("settings_clear_stored_key_confirm_title")}</DialogTitle>
        <DialogDescription id="clear-provider-credential-description">
          {t("settings_clear_stored_key_confirm_description")}
        </DialogDescription>
        {error ? (
          <p className="rs-notice rs-notice--danger" role="alert">
            {t("settings_clear_stored_key_error")}
          </p>
        ) : null}
        <div className="rs-dialog-actions">
          <Button disabled={pending} onClick={onClose} variant="secondary">
            {t("settings_cancel")}
          </Button>
          <Button disabled={pending} onClick={onConfirm} variant="danger">
            {t("settings_clear_stored_key_confirm")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

import { X } from "lucide-react"
import { Dialog as DialogPrimitive } from "radix-ui"

import { cn } from "../../lib/utils"
import { Button } from "./button"

export const Dialog = DialogPrimitive.Root
export const DialogTrigger = DialogPrimitive.Trigger
export const DialogTitle = ({
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Title>): React.JSX.Element => (
  <DialogPrimitive.Title className={cn("rs-dialog__title", className)} {...props} />
)
export const DialogDescription = ({
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Description>): React.JSX.Element => (
  <DialogPrimitive.Description className={cn("rs-dialog__description", className)} {...props} />
)

export function DialogContent({
  children,
  className,
  closeLabel = "Close dialog",
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Content> & {
  readonly closeLabel?: string | undefined
}): React.JSX.Element {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="rs-dialog__overlay" />
      <DialogPrimitive.Content className={cn("rs-dialog", className)} {...props}>
        {children}
        <DialogPrimitive.Close asChild>
          <Button
            aria-label={closeLabel}
            className="rs-dialog__close"
            size="icon"
            variant="secondary"
          >
            <X aria-hidden="true" size={18} />
          </Button>
        </DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  )
}

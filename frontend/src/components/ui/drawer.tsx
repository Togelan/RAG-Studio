import { Dialog as DialogPrimitive } from "radix-ui"

import { cn } from "../../lib/utils"

export const Drawer = DialogPrimitive.Root
export const DrawerTrigger = DialogPrimitive.Trigger
export const DrawerTitle = DialogPrimitive.Title

export function DrawerContent({
  children,
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Content>): React.JSX.Element {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="rs-drawer__overlay" />
      <DialogPrimitive.Content className={cn("rs-drawer", className)} {...props}>
        {children}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  )
}

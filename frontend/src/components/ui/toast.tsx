import { Toast as ToastPrimitive } from "radix-ui"

import { cn } from "../../lib/utils"

export const ToastProvider = ToastPrimitive.Provider
export const ToastViewport = ({
  className,
  ...props
}: React.ComponentProps<typeof ToastPrimitive.Viewport>): React.JSX.Element => (
  <ToastPrimitive.Viewport className={cn("rs-toast-viewport", className)} {...props} />
)

export function Toast({
  className,
  ...props
}: React.ComponentProps<typeof ToastPrimitive.Root>): React.JSX.Element {
  return <ToastPrimitive.Root className={cn("rs-toast", className)} {...props} />
}

export const ToastTitle = ({
  className,
  ...props
}: React.ComponentProps<typeof ToastPrimitive.Title>): React.JSX.Element => (
  <ToastPrimitive.Title className={cn("rs-toast__title", className)} {...props} />
)
export const ToastDescription = ({
  className,
  ...props
}: React.ComponentProps<typeof ToastPrimitive.Description>): React.JSX.Element => (
  <ToastPrimitive.Description className={cn("rs-toast__description", className)} {...props} />
)

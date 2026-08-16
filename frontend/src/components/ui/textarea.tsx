import { forwardRef } from "react"

import { cn } from "../../lib/utils"

export const Textarea = forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(function Textarea({ className, ...props }, ref): React.JSX.Element {
  return <textarea className={cn("rs-textarea", className)} ref={ref} {...props} />
})

import { forwardRef } from "react"

import { cn } from "../../lib/utils"

export const Input = forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...props }, ref): React.JSX.Element {
    return <input className={cn("rs-input", className)} ref={ref} {...props} />
  },
)

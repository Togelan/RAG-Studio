import { cva, type VariantProps } from "class-variance-authority"
import { forwardRef } from "react"

import { cn } from "../../lib/utils"

const buttonVariants = cva("rs-button", {
  defaultVariants: { size: "default", variant: "primary" },
  variants: {
    size: { compact: "rs-button--compact", default: "", icon: "rs-button--icon" },
    variant: {
      ai: "rs-button--ai",
      danger: "rs-button--danger",
      primary: "",
      secondary: "rs-button--secondary",
    },
  },
})

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, size, type = "button", variant, ...props },
  ref,
): React.JSX.Element {
  return (
    <button
      className={cn(buttonVariants({ className, size, variant }))}
      ref={ref}
      type={type}
      {...props}
    />
  )
})

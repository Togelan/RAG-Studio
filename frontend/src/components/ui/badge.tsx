import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "../../lib/utils"

const badgeVariants = cva("rs-badge", {
  defaultVariants: { variant: "neutral" },
  variants: {
    variant: {
      ai: "rs-badge--ai",
      danger: "rs-badge--danger",
      neutral: "",
      success: "rs-badge--success",
      warning: "rs-badge--warning",
    },
  },
})

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps): React.JSX.Element {
  return (
    <span className={cn(badgeVariants({ className, variant }))} data-variant={variant} {...props} />
  )
}

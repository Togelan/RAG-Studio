import { cn } from "../../lib/utils"

export function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>): React.JSX.Element {
  return <div aria-hidden="true" className={cn("rs-skeleton", className)} {...props} />
}

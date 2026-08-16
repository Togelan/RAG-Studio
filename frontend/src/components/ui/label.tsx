import { Label as LabelPrimitive } from "radix-ui"

import { cn } from "../../lib/utils"

export function Label({
  className,
  ...props
}: React.ComponentProps<typeof LabelPrimitive.Root>): React.JSX.Element {
  return <LabelPrimitive.Root className={cn("rs-label", className)} {...props} />
}

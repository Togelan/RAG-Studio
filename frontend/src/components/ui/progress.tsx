import { Progress as ProgressPrimitive } from "radix-ui"

import { cn } from "../../lib/utils"

export interface ProgressProps extends React.ComponentProps<typeof ProgressPrimitive.Root> {
  label: string
}

type ProgressStyle = React.CSSProperties & {
  "--rs-progress-value": string
}

export function Progress({
  className,
  label,
  max = 100,
  style,
  value,
  ...props
}: ProgressProps): React.JSX.Element {
  const percentage =
    value === null || value === undefined ? 0 : Math.max(0, Math.min(100, (value / max) * 100))
  const progressStyle: ProgressStyle = {
    ...style,
    "--rs-progress-value": `${percentage}%`,
  }
  return (
    <ProgressPrimitive.Root
      aria-label={label}
      className={cn("rs-progress", className)}
      max={max}
      style={progressStyle}
      value={value}
      {...props}
    >
      <ProgressPrimitive.Indicator className="rs-progress__indicator" />
    </ProgressPrimitive.Root>
  )
}

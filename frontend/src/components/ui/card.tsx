import { cn } from "../../lib/utils"

export function Card({
  className,
  ...props
}: React.HTMLAttributes<HTMLElement>): React.JSX.Element {
  return <section className={cn("rs-card", className)} {...props} />
}

export function CardHeader({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>): React.JSX.Element {
  return <div className={cn("rs-card__header", className)} {...props} />
}

export function CardTitle({
  className,
  ...props
}: React.HTMLAttributes<HTMLHeadingElement>): React.JSX.Element {
  return <h2 className={cn("rs-card__title", className)} {...props} />
}

export function CardContent({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>): React.JSX.Element {
  return <div className={cn("rs-card__content", className)} {...props} />
}

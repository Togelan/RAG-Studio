import { cn } from "../../lib/utils"

export function Table({
  className,
  ...props
}: React.TableHTMLAttributes<HTMLTableElement>): React.JSX.Element {
  return (
    <div className="rs-table-wrap">
      <table className={cn("rs-table", className)} {...props} />
    </div>
  )
}

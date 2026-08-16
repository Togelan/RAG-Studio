import { ChevronDown } from "lucide-react"

import { cn } from "../../lib/utils"

export interface SelectOption {
  label: string
  value: string
}

export interface SelectProps
  extends Omit<React.SelectHTMLAttributes<HTMLSelectElement>, "children"> {
  options: readonly SelectOption[]
}

export function Select({ className, options, ...props }: SelectProps): React.JSX.Element {
  return (
    <span className="rs-select">
      <select className={cn("rs-select__control", className)} {...props}>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <ChevronDown aria-hidden="true" className="rs-select__icon" size={16} />
    </span>
  )
}

import { Check, ChevronDown, Languages } from "lucide-react"
import { useRef, useState } from "react"

import type { Locale } from "../../i18n/locale-inventory"
import "./locale-menu.css"

const localeCodes: readonly Locale[] = ["en", "ru"]

export function LocaleMenu({
  ariaLabel,
  locale,
  onLocaleChange,
  optionLabels,
}: {
  readonly ariaLabel: string
  readonly locale: Locale
  readonly onLocaleChange: (locale: Locale) => Promise<void>
  readonly optionLabels: Readonly<Record<Locale, string>>
}): React.JSX.Element {
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)

  const selectLocale = (nextLocale: Locale): void => {
    setOpen(false)
    if (nextLocale !== locale) void onLocaleChange(nextLocale)
  }

  const handleTriggerKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>): void => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault()
      setOpen((wasOpen) => !wasOpen)
      return
    }
    if (event.key === "Escape") {
      event.preventDefault()
      setOpen(false)
      event.currentTarget.focus()
    }
  }

  const closePanelOnEscape = (event: React.KeyboardEvent<HTMLButtonElement>): void => {
    if (event.key !== "Escape") return
    event.preventDefault()
    setOpen(false)
    triggerRef.current?.focus()
  }

  return (
    <div className={`rs-locale-menu${open ? " rs-locale-menu--open" : ""}`}>
      <button
        aria-expanded={open}
        aria-haspopup="true"
        aria-label={ariaLabel}
        className="rs-locale-menu__trigger"
        onClick={() => setOpen((wasOpen) => !wasOpen)}
        onKeyDown={handleTriggerKeyDown}
        ref={triggerRef}
        type="button"
      >
        <Languages aria-hidden="true" size={16} />
        <span>{locale.toUpperCase()}</span>
        <ChevronDown aria-hidden="true" size={14} />
      </button>
      {open ? (
        <div className="rs-locale-menu__panel">
          {localeCodes.map((candidate) => {
            const selected = candidate === locale
            return (
              <button
                aria-pressed={selected}
                key={candidate}
                onClick={() => selectLocale(candidate)}
                onKeyDown={closePanelOnEscape}
                type="button"
              >
                <span>{optionLabels[candidate]}</span>
                {selected ? <Check aria-hidden="true" size={16} /> : null}
              </button>
            )
          })}
        </div>
      ) : null}
    </div>
  )
}

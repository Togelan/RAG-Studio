import { createContext, useContext, useEffect, useMemo, useState } from "react"
import type { Locale, TranslationKey } from "../i18n/locale-inventory"
import {
  createLocaleMessageFormatter,
  type LocaleMessageFormatter,
  type LocaleRuntime,
  useLocale,
} from "../i18n/locale-runtime"

type LocaleContextValue = {
  readonly locale: Locale
  readonly setLocale: (locale: Locale) => Promise<void>
  readonly t: (key: TranslationKey) => string
  readonly format: LocaleMessageFormatter
}

class MissingLocaleProviderError extends Error {
  constructor() {
    super("RAG-Studio locale provider is unavailable")
    this.name = "MissingLocaleProviderError"
  }
}

const LocaleContext = createContext<LocaleContextValue | null>(null)

export function LocaleProvider({
  children,
  runtime,
}: {
  readonly children: React.ReactNode
  readonly runtime: LocaleRuntime
}): React.JSX.Element {
  const localeState = useLocale(runtime)
  const [switchFailure, setSwitchFailure] = useState(false)

  useEffect(() => {
    document.documentElement.lang = localeState.locale
  }, [localeState.locale])

  const value = useMemo<LocaleContextValue>(
    () => ({
      locale: localeState.locale,
      setLocale: async (locale: Locale): Promise<void> => {
        const result = await runtime.setLocale(locale)
        setSwitchFailure(result.kind === "failure")
      },
      t: runtime.translate,
      format: createLocaleMessageFormatter(localeState.translations),
    }),
    [localeState, runtime],
  )

  return (
    <LocaleContext.Provider value={value}>
      {children}
      {switchFailure ? (
        <p className="rs-visually-hidden" role="status">
          {value.t("locale_update_unavailable")}
        </p>
      ) : null}
    </LocaleContext.Provider>
  )
}

export function useLocaleContext(): LocaleContextValue {
  const value = useContext(LocaleContext)
  if (value === null) {
    throw new MissingLocaleProviderError()
  }
  return value
}

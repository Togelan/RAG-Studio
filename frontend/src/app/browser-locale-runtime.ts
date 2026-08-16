import englishLocale from "../../../src/api/locales/en.json"
import russianLocale from "../../../src/api/locales/ru.json"

import type { Locale } from "../i18n/locale-inventory"
import {
  createLocaleApiClient,
  createLocaleRuntime,
  createLocaleTranslations,
  type LocaleRuntime,
  type LocaleTranslations,
  persistBrowserLocale,
  resolveBrowserLocale,
} from "../i18n/locale-runtime"

const INITIAL_LOCALE_BUNDLES = {
  en: englishLocale,
  ru: russianLocale,
} as const satisfies Readonly<Record<Locale, unknown>>

function localeTranslations(locale: Locale): LocaleTranslations {
  const translations = createLocaleTranslations(INITIAL_LOCALE_BUNDLES[locale])

  if (translations === null) {
    throw new Error("Generated locale inventory does not match the bundled locale data")
  }

  return translations
}

const BUNDLED_TRANSLATIONS = {
  en: localeTranslations("en"),
  ru: localeTranslations("ru"),
} as const satisfies Readonly<Record<Locale, LocaleTranslations>>

export function createBrowserLocaleRuntime(): LocaleRuntime {
  const { locale: initialLocale } = resolveBrowserLocale()
  return createLocaleRuntime({
    gateway: createLocaleApiClient(),
    initialLocale,
    initialTranslations: BUNDLED_TRANSLATIONS[initialLocale],
    translationsByLocale: BUNDLED_TRANSLATIONS,
    persistLocale: persistBrowserLocale,
  })
}

import type { Locale } from "./locale-inventory"

export const LOCALE_STORAGE_KEY = "rag-studio-locale"

export function readStoredLocale(): string | null {
  try {
    return window.localStorage.getItem(LOCALE_STORAGE_KEY)
  } catch (error) {
    if (error instanceof DOMException) {
      return null
    }
    throw error
  }
}

export function persistBrowserLocale(locale: Locale): void {
  try {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, locale)
  } catch (error) {
    if (!(error instanceof DOMException)) {
      throw error
    }
  }
}

import { afterEach, beforeEach, describe, expect, it } from "vitest"
import englishLocale from "../../../src/api/locales/en.json"
import russianLocale from "../../../src/api/locales/ru.json"

import { createBrowserLocaleRuntime } from "./browser-locale-runtime"

const WELCOME_KEYS = ["welcome.get_started", "welcome.video_placeholder"] as const

function resetBrowserLocale(): void {
  window.localStorage.clear()
  window.history.replaceState({}, "", "/")
}

beforeEach(() => {
  resetBrowserLocale()
})

afterEach(() => {
  resetBrowserLocale()
})

describe("browser locale first paint", () => {
  it.each([
    ["en", englishLocale],
    ["ru", russianLocale],
  ] as const)(
    "has every Welcome translation before the %s network response",
    (locale, translations) => {
      window.history.replaceState({}, "", `/?lang=${locale}`)

      const runtime = createBrowserLocaleRuntime()

      expect(runtime.getState().locale).toBe(locale)
      for (const key of WELCOME_KEYS) {
        expect(runtime.translate(key)).toBe(translations[key])
        expect(runtime.translate(key)).not.toBe(key)
      }
    },
  )
})

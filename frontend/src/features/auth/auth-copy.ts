import type { Locale } from "../../i18n/locale-inventory"
import { getSaasCopy } from "../saas/saas-copy"

const introCopy = {
  en: "A trusted place to configure and test your company knowledge assistants.",
  ru: "Надёжное место для настройки и проверки помощников на знаниях компании.",
} satisfies Readonly<Record<Locale, string>>

export function getAuthCopy(locale: Locale): ReturnType<typeof getSaasCopy> & {
  readonly introduction: string
} {
  return { ...getSaasCopy(locale), introduction: introCopy[locale] }
}

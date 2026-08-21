import { Sparkles } from "lucide-react"
import { Link } from "react-router-dom"

import { useLocaleContext } from "../../app/locale-provider"
import { LocaleMenu } from "../../components/shell/locale-menu"

export function PublicAuthShell({
  children,
}: {
  readonly children: React.ReactNode
}): React.JSX.Element {
  const { locale, setLocale, t } = useLocaleContext()

  return (
    <div className="rs-public-auth">
      <header className="rs-public-auth__header">
        <Link aria-label="RAG-Studio" className="rs-public-auth__brand" to="/">
          <Sparkles aria-hidden="true" size={20} />
          <span>RAG-Studio</span>
        </Link>
        <LocaleMenu
          ariaLabel={t("aria_lang_selector")}
          locale={locale}
          onLocaleChange={setLocale}
          optionLabels={{ en: t("aria_english"), ru: t("aria_russian") }}
        />
      </header>
      <main className="rs-public-auth__main">{children}</main>
    </div>
  )
}

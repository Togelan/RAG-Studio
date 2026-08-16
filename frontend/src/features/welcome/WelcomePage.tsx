import { ArrowRight, CirclePlay } from "lucide-react"
import { Link, useLocation } from "react-router-dom"

import { useLocaleContext } from "../../app/locale-provider"
import "./welcome-page.css"

function settingsPath(pathname: string): string {
  return pathname === "/app" || pathname.startsWith("/app/") ? "/app/settings" : "/settings"
}

export function WelcomePage(): React.JSX.Element {
  const { t } = useLocaleContext()
  const { pathname } = useLocation()

  return (
    <div className="rs-welcome">
      <div className="rs-welcome__hero">
        <p className="rs-welcome__subtitle">{t("welcome_subtitle")}</p>
        <Link className="rs-button rs-welcome__cta" to={settingsPath(pathname)}>
          <span>{t("welcome.get_started")}</span>
          <ArrowRight aria-hidden="true" size={18} />
        </Link>
      </div>
      <section
        aria-disabled="true"
        aria-labelledby="welcome-tutorial-title"
        className="rs-welcome__tutorial"
      >
        <div className="rs-welcome__tutorial-icon">
          <CirclePlay aria-hidden="true" size={30} />
        </div>
        <div className="rs-welcome__tutorial-copy">
          <p className="rs-welcome__tutorial-label">RAG-Studio</p>
          <h2 id="welcome-tutorial-title">{t("welcome.video_placeholder")}</h2>
        </div>
      </section>
    </div>
  )
}
